"""Pure, bounded, deterministic and conservative M12 route solver."""

from __future__ import annotations

import ast
import heapq
import json
import math
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import cast

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
type _RankKey = tuple[int | str, ...]
type _MaterialPrefixSignature = tuple[int, int]
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
class _ExactLoopAcceleration:
    cycle_edges: tuple[CanonicalEdge, ...]
    repetitions: int
    effect_facts: tuple[CanonicalFact, ...]
    suppressed_edge_id: str

    @property
    def edge(self) -> CanonicalEdge:
        return self.cycle_edges[0]


@dataclass(frozen=True)
class _TargetAnchor:
    node_id: str
    occurrence_id: str | None = None
    required_edge_id: str | None = None


@dataclass(frozen=True)
class _ValueSource:
    effect_ids: tuple[str, ...]
    effect_counts: tuple[tuple[str, int], ...]
    last_effect_id: str | None
    depends_on_entry_precondition: bool = False

    @property
    def repeated_count(self) -> int:
        if self.last_effect_id is None:
            return 0
        return dict(self.effect_counts)[self.last_effect_id]


type _NumericBound = tuple[int | float, bool, tuple[str, ...]]
type _ExcludedLiteral = tuple[StateScalar, tuple[str, ...]]


@dataclass(frozen=True)
class _VariableConstraint:
    """One normalized, bounded conjunction for a supported state variable."""

    variable_key: str
    equality: tuple[StateScalar, ...] = ()
    equality_fact_ids: tuple[str, ...] = ()
    exclusions: tuple[_ExcludedLiteral, ...] = ()
    lower: _NumericBound | None = None
    upper: _NumericBound | None = None


@dataclass(frozen=True)
class _ConstraintState:
    """Chronological supported gate constraints retained in deterministic order."""

    variables: tuple[_VariableConstraint, ...] = ()

    def for_key(self, variable_key: str) -> _VariableConstraint:
        return next(
            (
                item
                for item in self.variables
                if item.variable_key == variable_key
            ),
            _VariableConstraint(variable_key),
        )

    def replacing(self, constraint: _VariableConstraint) -> _ConstraintState:
        retained = [
            item for item in self.variables if item.variable_key != constraint.variable_key
        ]
        retained.append(constraint)
        return _ConstraintState(
            tuple(sorted(retained, key=lambda item: item.variable_key))
        )

    def without(self, variable_key: str) -> _ConstraintState:
        return _ConstraintState(
            tuple(item for item in self.variables if item.variable_key != variable_key)
        )

    def normalized_key(self) -> tuple[object, ...]:
        return tuple(
            (
                item.variable_key,
                item.equality,
                item.equality_fact_ids,
                item.exclusions,
                item.lower,
                item.upper,
            )
            for item in self.variables
        )


@dataclass(frozen=True)
class _ConstraintTerm:
    variable_key: str
    operator: str
    value: StateScalar


@dataclass(frozen=True)
class _InternedSequenceRecord:
    parent_id: int | None
    value: str | None


class _InternedSequenceStore:
    """Intern exact material sequences with one bounded record per new token."""

    def __init__(self) -> None:
        self._records = [_InternedSequenceRecord(None, None)]
        self._index: dict[tuple[int, str], int] = {}

    def append(self, parent_id: int, value: str) -> tuple[int, bool]:
        key = (parent_id, value)
        existing = self._index.get(key)
        if existing is not None:
            return existing, False
        sequence_id = len(self._records)
        self._records.append(_InternedSequenceRecord(parent_id, value))
        self._index[key] = sequence_id
        return sequence_id, True


@dataclass(frozen=True)
class _RoutePrefix:
    """One parent-linked retained route step plus bounded incremental summaries."""

    parent_id: int | None
    node_id: str
    incoming_edge_id: str | None
    incoming_repetitions: int
    edge_count: int
    scene_count: int
    last_scene_id: str | None
    scene_signature_id: int
    material_edge_signature_id: int
    acceleration_group_id: str | None
    acceleration_repetitions: int | None
    acceleration_effect_ids: tuple[str, ...]
    accounting_units: int


class _RoutePrefixStore:
    """Linear-growth parent pointers; full paths exist only for accepted routes."""

    def __init__(self, start_node_id: str, scene_by_node: Mapping[str, str]) -> None:
        self._scenes = _InternedSequenceStore()
        self._material_edges = _InternedSequenceStore()
        start_scene = scene_by_node.get(start_node_id)
        scene_signature = 0
        sequence_units = 0
        if start_scene is not None:
            scene_signature, created = self._scenes.append(0, start_scene)
            sequence_units += 2 if created else 0
        self._records = [
            _RoutePrefix(
                None,
                start_node_id,
                None,
                0,
                0,
                1 if start_scene is not None else 0,
                start_scene,
                scene_signature,
                0,
                None,
                None,
                (),
                13 + sequence_units,
            )
        ]

    def __len__(self) -> int:
        return len(self._records)

    def record(self, prefix_id: int) -> _RoutePrefix:
        return self._records[prefix_id]

    def append(
        self,
        parent_id: int,
        node_id: str,
        edge_id: str,
        *,
        scene_id: str | None,
        material_edge: bool,
        repetitions: int = 1,
        acceleration_group_id: str | None = None,
        acceleration_repetitions: int | None = None,
        acceleration_effect_ids: tuple[str, ...] = (),
    ) -> int:
        if repetitions < 1:
            raise ValueError("route-prefix repetitions must be positive")
        parent = self.record(parent_id)
        scene_signature = parent.scene_signature_id
        material_signature = parent.material_edge_signature_id
        scene_count = parent.scene_count
        last_scene = parent.last_scene_id
        sequence_units = 0
        if scene_id is not None and scene_id != last_scene:
            scene_signature, created = self._scenes.append(scene_signature, scene_id)
            scene_count += 1
            last_scene = scene_id
            sequence_units += 2 if created else 0
        if material_edge:
            for _ in range(repetitions):
                material_signature, created = self._material_edges.append(
                    material_signature, edge_id
                )
                sequence_units += 2 if created else 0
        prefix_id = len(self._records)
        self._records.append(
            _RoutePrefix(
                parent_id,
                node_id,
                edge_id,
                repetitions,
                parent.edge_count + repetitions,
                scene_count,
                last_scene,
                scene_signature,
                material_signature,
                acceleration_group_id,
                acceleration_repetitions,
                acceleration_effect_ids,
                13 + len(acceleration_effect_ids) + sequence_units,
            )
        )
        return prefix_id

    def last_edge_id(self, prefix_id: int) -> str | None:
        return self.record(prefix_id).incoming_edge_id

    def transition_count(self, prefix_id: int, edge_id: str) -> int:
        total = 0
        current: int | None = prefix_id
        while current is not None:
            record = self.record(current)
            if record.incoming_edge_id == edge_id:
                total += record.incoming_repetitions
            current = record.parent_id
        return total

    def transition_counts(self, prefix_id: int) -> dict[str, int]:
        result: dict[str, int] = {}
        current: int | None = prefix_id
        while current is not None:
            record = self.record(current)
            if record.incoming_edge_id is not None:
                result[record.incoming_edge_id] = (
                    result.get(record.incoming_edge_id, 0)
                    + record.incoming_repetitions
                )
            current = record.parent_id
        return result

    def acceleration_summaries(
        self, prefix_id: int
    ) -> dict[str, tuple[int, set[str], set[str]]]:
        result: dict[str, tuple[int, set[str], set[str]]] = {}
        current: int | None = prefix_id
        while current is not None:
            record = self.record(current)
            if record.acceleration_group_id is not None:
                count, edge_ids, effect_ids = result.setdefault(
                    record.acceleration_group_id,
                    (0, set(), set()),
                )
                if record.acceleration_repetitions is not None:
                    count = record.acceleration_repetitions
                if record.incoming_edge_id is not None:
                    edge_ids.add(record.incoming_edge_id)
                effect_ids.update(record.acceleration_effect_ids)
                result[record.acceleration_group_id] = (count, edge_ids, effect_ids)
            current = record.parent_id
        return result

    def reconstruct(self, prefix_id: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
        chain: list[_RoutePrefix] = []
        current: int | None = prefix_id
        while current is not None:
            record = self.record(current)
            chain.append(record)
            current = record.parent_id
        chain.reverse()
        node_ids = [chain[0].node_id]
        edge_ids: list[str] = []
        for record in chain[1:]:
            assert record.incoming_edge_id is not None
            edge_ids.extend((record.incoming_edge_id,) * record.incoming_repetitions)
            node_ids.extend((record.node_id,) * record.incoming_repetitions)
        return tuple(node_ids), tuple(edge_ids)

    def accounting_between(self, parent_id: int, child_id: int) -> int:
        total = 0
        current: int | None = child_id
        while current is not None and current != parent_id:
            record = self.record(current)
            total += record.accounting_units
            current = record.parent_id
        if current != parent_id:
            raise ValueError("route prefix is not descended from the retained parent")
        return total


@dataclass
class _SearchState:
    node_id: str
    values: dict[str, object]
    value_sources: dict[str, _ValueSource]
    initial_kinds: dict[str, InitialStateValue]
    constraints: _ConstraintState
    prefix_id: int
    requirements: tuple[RequirementAttribution, ...]
    warnings: tuple[str, ...]
    call_stack: tuple[str, ...]
    selected_occurrence_id: str | None
    persistent_lane_ids: tuple[str, ...]
    loop_count: int
    suppressed_loop_edge_id: str | None


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
    supplied_initial = {item.variable.key: item for item in initial_state}
    for item in _authoritative_initial_values(graph, selected_start):
        supplied_initial.setdefault(item.variable.key, item)
    resolved_initial = tuple(sorted(supplied_initial.values(), key=lambda item: item.variable))
    _validate_initial_state(graph, selected_start, resolved_initial)
    _map_destination(graph, scene_model, destination)
    return RouteRequest(
        source_generation=graph.source_generation,
        canonical_schema=CANONICAL_GRAPH_SCHEMA,
        canonical_hash=authority_hash,
        scene_schema=M11_SCENE_MODEL_SCHEMA,
        scene_hash=scene_model.structural_hash,
        start_node_id=selected_start,
        destination=destination,
        initial_state=resolved_initial,
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
    resume_predecessors = _call_resume_predecessors(structural_edges)

    target_node_ids = {item.node_id for item in anchors}
    projection = numeric_projection(
        graph,
        target_node_ids,
        incoming,
        fact_by_id,
        resume_predecessors=resume_predecessors,
    )
    target_cone_nodes = _reverse_nodes(
        target_node_ids, incoming, resume_predecessors=resume_predecessors
    )
    target_reverse_nodes = _resolved_reverse_nodes(
        target_node_ids, incoming, resume_predecessors=resume_predecessors
    )
    values, value_sources, initial_kinds = _initial_values(
        graph,
        request.start_node_id,
        request.initial_state,
        projection,
    )
    constraints = _constraints_from_values(values, value_sources)
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
    prefix_store = _RoutePrefixStore(request.start_node_id, scene_by_node)
    start = _SearchState(
        request.start_node_id,
        values,
        value_sources,
        initial_kinds,
        constraints,
        0,
        (),
        (),
        (),
        None,
        (),
        0,
        None,
    )
    frontier: list[tuple[tuple[int | str, ...], int, _SearchState]] = []
    serial = 0
    heapq.heappush(
        frontier,
        (
            _partial_rank(
                start, prefix_store, minimum_persistent_commitments
            ),
            serial,
            start,
        ),
    )
    retained: dict[
        tuple[object, ...],
        list[tuple[_RankKey, _MaterialPrefixSignature]],
    ] = {}
    retained_count = 0
    candidates: dict[tuple[object, ...], RouteAlternative] = {}
    expanded = 0
    peak_frontier = 1
    accounting = _accounting_units(start) + prefix_store.record(0).accounting_units
    limit_hit: str | None = None
    bounded_limit_hit: str | None = None
    expanded_node_ids: set[str] = set()
    traversed_edge_ids: set[str] = set()
    contradiction_fact_ids: set[str] = set()
    contradiction_edge_ids: set[str] = set()
    unsupported_block = False
    best_route_proven = False
    alternative_limit_hit = False
    candidate_goal = request.limits.alternatives + 1

    def record_candidates(candidate_state: _SearchState) -> bool:
        matching = [
            anchor
            for anchor in anchors
            if anchor.node_id == candidate_state.node_id
            and (
                anchor.required_edge_id is None
                or (
                    prefix_store.last_edge_id(candidate_state.prefix_id)
                    == anchor.required_edge_id
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
                prefix_store,
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
        if cancelled is not None and cancelled():
            return SolveAttempt(None, cancelled=True, diagnostic="cancelled before completion")
        _, _, state = heapq.heappop(frontier)
        key = _state_key(state, projection)
        prefix_signature = _material_prefix_signature(state, prefix_store)
        state_rank = _partial_rank(
            state, prefix_store, minimum_persistent_commitments
        )
        retained_bucket = retained.setdefault(key, [])
        matching_index = next(
            (
                index
                for index, (_, signature) in enumerate(retained_bucket)
                if signature == prefix_signature
            ),
            None,
        )
        if matching_index is not None:
            previous_rank, _ = retained_bucket[matching_index]
            if previous_rank <= state_rank:
                continue
            retained_bucket[matching_index] = (state_rank, prefix_signature)
        elif len(retained_bucket) < candidate_goal:
            retained_bucket.append((state_rank, prefix_signature))
            retained_count += 1
        else:
            alternative_limit_hit = True
            worst_index = max(
                range(len(retained_bucket)),
                key=lambda index: retained_bucket[index],
            )
            if retained_bucket[worst_index] <= (state_rank, prefix_signature):
                continue
            retained_bucket[worst_index] = (state_rank, prefix_signature)
        if retained_count > request.limits.retained_states:
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

        acceleration = _exact_loop_acceleration(
            state,
            outgoing,
            node_by_id,
            fact_by_id,
            projection,
            target_cone_nodes,
            anchors,
        )
        accelerated_edge_id = acceleration.edge.id if acceleration is not None else None
        traversal_options: list[
            tuple[CanonicalEdge, bool, _ExactLoopAcceleration | None]
        ] = [
            (edge, False, None)
            for edge in outgoing.get(state.node_id, ())
            if edge.target_id in target_cone_nodes
            and _matches_target_entry_context(edge, anchors)
            and edge.id != state.suppressed_loop_edge_id
            and edge.id != accelerated_edge_id
        ]
        if acceleration is not None:
            traversal_options.append((acceleration.edge, False, acceleration))
        prior_edge_id = prefix_store.last_edge_id(state.prefix_id)
        if state.call_stack and prior_edge_id is not None:
            prior_edge = edge_by_id[prior_edge_id]
            if (
                prior_edge.kind == "call_return"
                and prior_edge.attributes.get("call_site_id") is None
                and state.call_stack[-1] in call_summaries
                and call_summaries[state.call_stack[-1]].target_id in target_cone_nodes
            ):
                traversal_options.append(
                    (call_summaries[state.call_stack[-1]], True, None)
                )
        traversal_options.sort(key=lambda item: (item[0].id, item[1], item[2] is None))
        for edge, is_resume, accelerated in traversal_options:
            traversed_edge_ids.add(edge.id)
            next_state: _SearchState | None
            contradiction_fact_ids_for_edge: tuple[str, ...]
            traversal_limit: str | None
            if accelerated is not None:
                required_prefixes = (
                    len(accelerated.cycle_edges) * accelerated.repetitions
                )
                if len(prefix_store) + required_prefixes > request.limits.prefix_records:
                    next_state = None
                    traversal_limit = "prefix_records"
                else:
                    next_state = _traverse_accelerated_loop(
                        state,
                        accelerated,
                        occurrence_edge,
                        lane_by_scene,
                        scene_by_node,
                        projection,
                        material_edge_ids,
                        prefix_store,
                    )
                    traversal_limit = None
                contradiction_fact_ids_for_edge = ()
            elif is_resume:
                next_state, traversal_limit = _resume_call_summary(
                    state,
                    edge,
                    node_by_id,
                    lane_by_scene,
                    scene_by_node,
                    material_edge_ids,
                    prefix_store,
                    request.limits,
                )
                contradiction_fact_ids_for_edge = ()
            else:
                next_state, contradiction_fact_ids_for_edge, traversal_limit = _traverse_edge(
                    state,
                    edge,
                    edge_by_id,
                    node_by_id,
                    fact_by_id,
                    occurrence_edge,
                    lane_by_scene,
                    scene_by_node,
                    projection,
                    material_edge_ids,
                    prefix_store,
                    request.limits,
                )
            if (
                contradiction_fact_ids_for_edge
                and edge.source_id in target_reverse_nodes
                and edge.target_id in target_reverse_nodes
            ):
                contradiction_fact_ids.update(contradiction_fact_ids_for_edge)
                contradiction_edge_ids.add(edge.id)
            if traversal_limit is not None:
                bounded_limit_hit = bounded_limit_hit or traversal_limit
                continue
            if next_state is None:
                if not contradiction_fact_ids_for_edge:
                    unsupported_block = True
                continue
            completed = record_candidates(next_state)
            if len(prefix_store) > request.limits.prefix_records:
                limit_hit = "prefix_records"
                break
            accounting += (
                _accounting_units(next_state)
                + prefix_store.accounting_between(state.prefix_id, next_state.prefix_id)
            )
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
                        prefix_store,
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
    if alternative_limit_hit:
        limit_hit = limit_hit or "alternatives"
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
        retained_states=min(retained_count, request.limits.retained_states),
        peak_frontier_states=min(peak_frontier, request.limits.frontier_states),
        prefix_records=min(len(prefix_store), request.limits.prefix_records),
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
    *,
    resume_predecessors: Mapping[str, Sequence[str]] | None = None,
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
        for predecessor in (resume_predecessors or {}).get(node_id, ()):
            if predecessor not in reverse_nodes:
                reverse_nodes.add(predecessor)
                pending.append(predecessor)
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

    if not any(item.id == start_node_id for item in graph.nodes):
        raise ValueError("initial state start context is unavailable")
    for item in initial_state:
        if item.kind is not InitialValueKind.KNOWN:
            continue
        if not _matching_initial_fact_ids(graph, start_node_id, item):
            raise ValueError(
                f"known initial value for {item.variable.key} lacks exact M10 initialization proof"
            )


def _authoritative_initial_values(
    graph: CanonicalGraph, start_node_id: str
) -> tuple[InitialStateValue, ...]:
    """Derive only unambiguous literal initialization facts owned by the M10 start."""

    start = next((item for item in graph.nodes if item.id == start_node_id), None)
    if start is None:
        return ()
    facts = {item.id: item for item in graph.facts}
    candidates: dict[str, list[tuple[StateVariableIdentity, StateScalar, CanonicalFact]]] = (
        defaultdict(list)
    )
    for fact_id in _strings(start.attributes.get("fact_ids")):
        fact = facts.get(fact_id)
        if fact is None:
            continue
        attributes = fact.attributes
        variable_name = attributes.get("variable")
        value = attributes.get("value")
        if (
            fact.kind != "effect"
            or fact.status != "proven"
            or attributes.get("initialization") is not True
            or attributes.get("operation") != "assignment"
            or not isinstance(variable_name, str)
            or not variable_name
            or not _is_scalar(value)
        ):
            continue
        identity = identity_from_name(variable_name)
        if identity.persistent is True:
            continue
        candidates[identity.key].append((identity, cast(StateScalar, value), fact))
    result: list[InitialStateValue] = []
    for records in candidates.values():
        values = {(type(value).__name__, repr(value)) for _, value, _ in records}
        if len(values) != 1:
            continue
        identity, value, selected_fact = min(records, key=lambda item: item[2].id)
        evidence_ids = tuple(sorted(selected_fact.evidence_ids))
        result.append(
            InitialStateValue(identity, InitialValueKind.KNOWN, value, evidence_ids)
        )
    return tuple(sorted(result, key=lambda item: item.variable))


def _matching_initial_fact_ids(
    graph: CanonicalGraph,
    start_node_id: str,
    item: InitialStateValue,
) -> tuple[str, ...]:
    if item.variable.persistent is True:
        return ()
    start = next((node for node in graph.nodes if node.id == start_node_id), None)
    if start is None:
        return ()
    start_fact_ids = set(_strings(start.attributes.get("fact_ids")))
    matching: list[str] = []
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
    return tuple(sorted(matching))


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
    graph: CanonicalGraph,
    start_node_id: str,
    items: Sequence[InitialStateValue],
    projection: NumericProjection,
) -> tuple[
    dict[str, object],
    dict[str, _ValueSource],
    dict[str, InitialStateValue],
]:
    values: dict[str, object] = {}
    sources: dict[str, _ValueSource] = {}
    initial: dict[str, InitialStateValue] = {}
    relevant = {item.key for item in projection.relevant_variables}
    for item in items:
        if item.variable.key not in relevant:
            continue
        initial[item.variable.key] = item
        if item.kind is not InitialValueKind.UNKNOWN:
            values[item.variable.key] = item.value
        if item.kind is InitialValueKind.KNOWN:
            matching = _matching_initial_fact_ids(graph, start_node_id, item)
            if matching:
                sources[item.variable.key] = _ValueSource(
                    (matching[0],),
                    ((matching[0], 1),),
                    matching[0],
                )
        elif item.kind is InitialValueKind.ENTRY_PRECONDITION:
            sources[item.variable.key] = _ValueSource((), (), None, True)
    return values, sources, initial


def _constraints_from_values(
    values: Mapping[str, object],
    sources: Mapping[str, _ValueSource],
) -> _ConstraintState:
    constraints = _ConstraintState()
    for variable_key in sorted(values):
        value = values[variable_key]
        if not _is_scalar(value):
            continue
        source = sources.get(variable_key)
        constraints = _constraint_with_exact_value(
            constraints,
            variable_key,
            cast(StateScalar, value),
            source.effect_ids if source is not None else (),
        )
    return constraints


def _constraint_with_exact_value(
    constraints: _ConstraintState,
    variable_key: str,
    value: StateScalar,
    fact_ids: Iterable[str],
) -> _ConstraintState:
    return constraints.replacing(
        _VariableConstraint(
            variable_key,
            equality=(value,),
            equality_fact_ids=tuple(sorted(set(fact_ids))),
        )
    )


def _supported_constraint_terms(expression: str) -> tuple[_ConstraintTerm, ...]:
    """Extract only a safe conjunction of names and literal comparisons."""

    try:
        root = ast.parse(expression, mode="eval").body
    except SyntaxError:
        return ()

    def collect(node: ast.expr) -> list[_ConstraintTerm]:
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            return [term for child in node.values for term in collect(child)]
        name = _qualified_name(node)
        if name is not None:
            return [_ConstraintTerm(identity_from_name(name).key, "eq", True)]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            operand_name = _qualified_name(node.operand)
            if operand_name is not None:
                return [
                    _ConstraintTerm(
                        identity_from_name(operand_name).key,
                        "eq",
                        False,
                    )
                ]
            return []
        if (
            not isinstance(node, ast.Compare)
            or len(node.ops) != 1
            or len(node.comparators) != 1
        ):
            return []
        operator = node.ops[0]
        left_name = _qualified_name(node.left)
        right = node.comparators[0]
        if left_name is not None and isinstance(right, ast.Constant):
            parsed_operator = _constraint_operator(operator)
            literal = right.value
        elif isinstance(node.left, ast.Constant):
            right_name = _qualified_name(right)
            if right_name is None:
                return []
            left_name = right_name
            parsed_operator = _reverse_constraint_operator(operator)
            literal = node.left.value
        else:
            return []
        if parsed_operator is None or not _is_scalar(literal):
            return []
        if parsed_operator in {"gt", "ge", "lt", "le"} and not _is_number(literal):
            return []
        return [
            _ConstraintTerm(
                identity_from_name(left_name).key,
                parsed_operator,
                cast(StateScalar, literal),
            )
        ]

    return tuple(collect(root))


def _constraint_operator(operator: ast.cmpop) -> str | None:
    return {
        ast.Eq: "eq",
        ast.NotEq: "ne",
        ast.Gt: "gt",
        ast.GtE: "ge",
        ast.Lt: "lt",
        ast.LtE: "le",
    }.get(type(operator))


def _reverse_constraint_operator(operator: ast.cmpop) -> str | None:
    return {
        ast.Eq: "eq",
        ast.NotEq: "ne",
        ast.Gt: "lt",
        ast.GtE: "le",
        ast.Lt: "gt",
        ast.LtE: "ge",
    }.get(type(operator))


def _intersect_supported_constraints(
    constraints: _ConstraintState,
    terms: Sequence[_ConstraintTerm],
    fact_id: str,
) -> tuple[_ConstraintState, tuple[str, ...]]:
    result = constraints
    for term in terms:
        result, contradiction_ids = _intersect_supported_constraint(
            result,
            term,
            fact_id,
        )
        if contradiction_ids:
            return constraints, contradiction_ids
    return result, ()


def _intersect_supported_constraint(
    constraints: _ConstraintState,
    term: _ConstraintTerm,
    fact_id: str,
) -> tuple[_ConstraintState, tuple[str, ...]]:
    current = constraints.for_key(term.variable_key)
    fact_ids = (fact_id,)
    equality = current.equality
    equality_fact_ids = current.equality_fact_ids
    exclusions = list(current.exclusions)
    lower = current.lower
    upper = current.upper

    if term.operator == "eq":
        if equality and not _literal_equal(equality[0], term.value):
            return constraints, _contradiction_ids(equality_fact_ids, fact_ids)
        excluded = _matching_exclusion(exclusions, term.value)
        if excluded is not None:
            return constraints, _contradiction_ids(excluded[1], fact_ids)
        lower_outcome = _value_satisfies_bound(term.value, lower, lower_bound=True)
        if lower_outcome is False and lower is not None:
            return constraints, _contradiction_ids(lower[2], fact_ids)
        upper_outcome = _value_satisfies_bound(term.value, upper, lower_bound=False)
        if upper_outcome is False and upper is not None:
            return constraints, _contradiction_ids(upper[2], fact_ids)
        if equality:
            equality_fact_ids = _contradiction_ids(equality_fact_ids, fact_ids)
        else:
            equality = (term.value,)
            equality_fact_ids = fact_ids
    elif term.operator == "ne":
        if equality and _literal_equal(equality[0], term.value):
            return constraints, _contradiction_ids(equality_fact_ids, fact_ids)
        excluded = _matching_exclusion(exclusions, term.value)
        if excluded is None:
            exclusions.append((term.value, fact_ids))
        else:
            exclusions[exclusions.index(excluded)] = (
                excluded[0],
                _contradiction_ids(excluded[1], fact_ids),
            )
    elif term.operator in {"gt", "ge", "lt", "le"}:
        assert _is_number(term.value)
        bound: _NumericBound = (
            cast(int | float, term.value),
            term.operator in {"ge", "le"},
            fact_ids,
        )
        is_lower = term.operator in {"gt", "ge"}
        if equality:
            outcome = _value_satisfies_bound(
                equality[0],
                bound,
                lower_bound=is_lower,
            )
            if outcome is False:
                return constraints, _contradiction_ids(equality_fact_ids, fact_ids)
        if is_lower:
            lower = _stronger_lower(lower, bound)
        else:
            upper = _stronger_upper(upper, bound)
        if lower is not None and upper is not None and _bounds_are_empty(lower, upper):
            return constraints, _contradiction_ids(lower[2], upper[2])
    else:
        return constraints, ()

    normalized = _VariableConstraint(
        term.variable_key,
        equality=equality,
        equality_fact_ids=tuple(sorted(set(equality_fact_ids))),
        exclusions=tuple(
            sorted(
                exclusions,
                key=lambda item: _literal_sort_key(item[0]),
            )
        ),
        lower=lower,
        upper=upper,
    )
    return constraints.replacing(normalized), ()


def _matching_exclusion(
    exclusions: Sequence[_ExcludedLiteral],
    value: StateScalar,
) -> _ExcludedLiteral | None:
    return next(
        (item for item in exclusions if _literal_equal(item[0], value)),
        None,
    )


def _stronger_lower(
    current: _NumericBound | None,
    candidate: _NumericBound,
) -> _NumericBound:
    if current is None or candidate[0] > current[0]:
        return candidate
    if candidate[0] < current[0]:
        return current
    inclusive = current[1] and candidate[1]
    return (
        current[0],
        inclusive,
        _contradiction_ids(current[2], candidate[2]),
    )


def _stronger_upper(
    current: _NumericBound | None,
    candidate: _NumericBound,
) -> _NumericBound:
    if current is None or candidate[0] < current[0]:
        return candidate
    if candidate[0] > current[0]:
        return current
    inclusive = current[1] and candidate[1]
    return (
        current[0],
        inclusive,
        _contradiction_ids(current[2], candidate[2]),
    )


def _bounds_are_empty(lower: _NumericBound, upper: _NumericBound) -> bool:
    return lower[0] > upper[0] or (
        lower[0] == upper[0] and not (lower[1] and upper[1])
    )


def _value_satisfies_bound(
    value: StateScalar,
    bound: _NumericBound | None,
    *,
    lower_bound: bool,
) -> bool | None:
    if bound is None:
        return True
    try:
        if lower_bound:
            return value >= bound[0] if bound[1] else value > bound[0]  # type: ignore[operator]
        return value <= bound[0] if bound[1] else value < bound[0]  # type: ignore[operator]
    except TypeError:
        return None


def _literal_equal(left: StateScalar, right: StateScalar) -> bool:
    return left == right


def _literal_sort_key(value: StateScalar) -> tuple[str, str]:
    return type(value).__name__, json.dumps(value, ensure_ascii=False, sort_keys=True)


def _contradiction_ids(*fact_id_groups: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({fact_id for group in fact_id_groups for fact_id in group}))


def _apply_node_effects(
    state: _SearchState,
    node: CanonicalNode,
    facts: Mapping[str, CanonicalFact],
    projection: NumericProjection,
) -> _SearchState:
    values = dict(state.values)
    sources = dict(state.value_sources)
    constraints = state.constraints
    warnings = list(state.warnings)
    relevant = {item.key for item in projection.relevant_variables}
    for fact_id in _strings(node.attributes.get("fact_ids")):
        fact = facts.get(fact_id)
        if fact is None or fact.kind != "effect":
            continue
        if fact.attributes.get("initialization") is True:
            continue
        constraints = _apply_effect(
            fact,
            values,
            sources,
            constraints,
            warnings,
            relevant,
        )
    return replace(
        state,
        values=values,
        value_sources=sources,
        constraints=constraints,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _exact_loop_acceleration(
    state: _SearchState,
    outgoing: Mapping[str, Sequence[CanonicalEdge]],
    nodes: Mapping[str, CanonicalNode],
    facts: Mapping[str, CanonicalFact],
    projection: NumericProjection,
    target_cone_nodes: set[str],
    anchors: Sequence[_TargetAnchor],
) -> _ExactLoopAcceleration | None:
    """Return one exact M10-authorized monotone cycle acceleration, if any."""

    node = nodes[state.node_id]
    loop_ids = set(_strings(node.attributes.get("loop_ids")))
    cycle_edges = _exact_structural_loop_cycle(state.node_id, outgoing, len(nodes))
    if not cycle_edges:
        return None

    relevant = {item.key for item in projection.relevant_variables}
    effect_facts: list[CanonicalFact] = []
    deltas: dict[str, int | float] = {}
    phase_deltas: dict[str, dict[str, int | float]] = {}
    phase_edge_counts: dict[str, int] = {}
    relevant_one_shot = False
    unresolved_write = False
    for edge_index, edge in enumerate(cycle_edges):
        phase_deltas[edge.source_id] = dict(deltas)
        phase_edge_counts[edge.source_id] = edge_index
        transition_effect_ids = [*_strings(edge.attributes.get("effect_ids"))]
        transition_effect_ids.extend(
            fact_id
            for fact_id in _strings(nodes[edge.target_id].attributes.get("fact_ids"))
            if facts.get(fact_id) is not None
            and facts[fact_id].attributes.get("initialization") is not True
        )
        for fact_id in transition_effect_ids:
            fact = facts.get(fact_id)
            if fact is None or fact.kind != "effect":
                unresolved_write = True
                continue
            variable_name = fact.attributes.get("variable")
            if not isinstance(variable_name, str) or not variable_name:
                unresolved_write = True
                continue
            variable_key = identity_from_name(variable_name).key
            if variable_key not in relevant:
                continue
            delta = _numeric_effect_delta(fact)
            if fact.status != "proven" or delta is None:
                relevant_one_shot = fact.status == "proven"
                unresolved_write = unresolved_write or fact.status != "proven"
                continue
            if not _is_number(state.values.get(variable_key, _UNKNOWN)):
                unresolved_write = True
                continue
            effect_facts.append(fact)
            deltas[variable_key] = deltas.get(variable_key, 0) + delta

    cycle_edge_ids = {item.id for item in cycle_edges}
    cycle_source_ids = {item.source_id for item in cycle_edges}
    exit_edges = tuple(
        edge
        for source_id in cycle_source_ids
        for edge in outgoing.get(source_id, ())
        if edge.id not in cycle_edge_ids
        and edge.target_id in target_cone_nodes
        and _matches_target_entry_context(edge, anchors)
    )
    stopping = _exact_stopping_repetitions(
        state.values,
        deltas,
        exit_edges,
        facts,
        phase_deltas,
        phase_edge_counts,
        len(cycle_edges),
    )
    repetitions = stopping[0] if stopping is not None else None
    authority_proven = bool(loop_ids) or node.kind is CanonicalNodeKind.LOOP
    decision = loop_acceleration_decision(
        LoopAccelerationSummary(
            same_transition_summary=(
                all(edge.resolved for edge in cycle_edges)
                and not any(
                    _strings(edge.attributes.get("gate_ids")) for edge in cycle_edges
                )
            ),
            same_structural_context=(
                authority_proven and cycle_edges[-1].target_id == state.node_id
            ),
            same_call_context=not any(
                edge.kind in {"call_enter", "call_summary", "call_return"}
                for edge in cycle_edges
            ),
            relevant_one_shot_change=relevant_one_shot,
            relevant_branch_change=any(
                _strings(edge.attributes.get("gate_ids")) for edge in cycle_edges
            ),
            unresolved_relevant_write=unresolved_write,
            repeated_effect_proven=bool(effect_facts) and bool(deltas),
            stopping_threshold_proven=repetitions is not None,
        )
    )
    if not decision.eligible or repetitions is None:
        return None
    assert stopping is not None
    stopping_source_id = stopping[1]
    suppressed_edge = next(
        (edge for edge in cycle_edges if edge.source_id == stopping_source_id),
        None,
    )
    if suppressed_edge is None:
        return None
    return _ExactLoopAcceleration(
        cycle_edges,
        repetitions,
        tuple(effect_facts),
        suppressed_edge.id,
    )


def _exact_structural_loop_cycle(
    start_node_id: str,
    outgoing: Mapping[str, Sequence[CanonicalEdge]],
    node_bound: int,
) -> tuple[CanonicalEdge, ...]:
    """Follow one unique resolved M10 loop-body/back path to the same anchor."""

    cycle: list[CanonicalEdge] = []
    current = start_node_id
    visited = {start_node_id}
    for _ in range(node_bound):
        internal = tuple(
            edge
            for edge in outgoing.get(current, ())
            if edge.resolved
            and (
                edge.kind in {"loop_body", "loop_back"}
                or "loop_back" in set(_strings(edge.attributes.get("semantic_roles")))
            )
        )
        if len(internal) != 1:
            return ()
        edge = internal[0]
        cycle.append(edge)
        current = edge.target_id
        if current == start_node_id:
            return tuple(cycle)
        if current in visited:
            return ()
        visited.add(current)
    return ()


def _numeric_effect_delta(fact: CanonicalFact) -> int | float | None:
    value = fact.attributes.get("value")
    operation = str(fact.attributes.get("operation", ""))
    if not _is_number(value) or operation not in {"increment", "decrement"}:
        return None
    assert isinstance(value, int | float) and not isinstance(value, bool)
    return value if operation == "increment" else -value


def _exact_stopping_repetitions(
    values: Mapping[str, object],
    deltas: Mapping[str, int | float],
    exit_edges: Sequence[CanonicalEdge],
    facts: Mapping[str, CanonicalFact],
    phase_deltas: Mapping[str, Mapping[str, int | float]],
    phase_edge_counts: Mapping[str, int],
    cycle_edge_count: int,
) -> tuple[int, str] | None:
    candidates: list[tuple[int, str, str, int]] = []
    for exit_edge in sorted(exit_edges, key=lambda item: item.id):
        exit_phase_deltas = phase_deltas.get(exit_edge.source_id)
        phase_edge_count = phase_edge_counts.get(exit_edge.source_id)
        if exit_phase_deltas is None or phase_edge_count is None:
            continue
        phase_values = _values_after_repetitions(values, exit_phase_deltas, 1)
        gate_ids = _strings(exit_edge.attributes.get("gate_ids"))
        if not exit_edge.resolved or not gate_ids:
            continue
        expressions: list[str] = []
        terms: list[_ConstraintTerm] = []
        supported = True
        for fact_id in gate_ids:
            fact = facts.get(fact_id)
            if fact is None or fact.kind != "requirement" or fact.status != "proven":
                supported = False
                break
            expression = str(fact.attributes.get("original_expression", ""))
            parsed_terms = _supported_constraint_terms(expression)
            if not parsed_terms or _safe_condition(expression, phase_values) is None:
                supported = False
                break
            expressions.append(expression)
            terms.extend(parsed_terms)
        if not supported or all(
            _safe_condition(item, phase_values) is True for item in expressions
        ):
            continue
        required: list[int] = []
        for term in terms:
            repetitions = _minimum_term_repetitions(term, phase_values, deltas)
            if repetitions is None:
                supported = False
                break
            required.append(repetitions)
        if not supported:
            continue
        repetitions = max(required, default=0)
        if repetitions < 1:
            continue
        projected = _values_after_repetitions(phase_values, deltas, repetitions)
        if not all(_safe_condition(item, projected) is True for item in expressions):
            continue
        emitted_edge_count = (repetitions * cycle_edge_count) + phase_edge_count
        candidates.append(
            (
                emitted_edge_count,
                exit_edge.id,
                exit_edge.source_id,
                repetitions,
            )
        )
    if not candidates:
        return None
    _edge_count, _exit_edge_id, source_id, repetitions = min(candidates)
    return repetitions, source_id


def _minimum_term_repetitions(
    term: _ConstraintTerm,
    values: Mapping[str, object],
    deltas: Mapping[str, int | float],
) -> int | None:
    current = values.get(term.variable_key, _UNKNOWN)
    if _constraint_term_truth(term, current) is True:
        return 0
    delta = deltas.get(term.variable_key)
    if not _is_number(current) or not _is_number(term.value) or not _is_number(delta):
        return None
    assert isinstance(current, int | float) and not isinstance(current, bool)
    assert isinstance(term.value, int | float) and not isinstance(term.value, bool)
    assert isinstance(delta, int | float) and not isinstance(delta, bool)
    if delta == 0:
        return None
    if term.operator == "eq":
        quotient = (term.value - current) / delta
        repetitions = int(quotient)
        return repetitions if repetitions > 0 and quotient == repetitions else None
    if term.operator == "ne":
        return 1
    if term.operator == "ge" and delta > 0:
        return max(1, math.ceil((term.value - current) / delta))
    if term.operator == "gt" and delta > 0:
        return max(1, math.floor((term.value - current) / delta) + 1)
    if term.operator == "le" and delta < 0:
        return max(1, math.ceil((current - term.value) / -delta))
    if term.operator == "lt" and delta < 0:
        return max(1, math.floor((current - term.value) / -delta) + 1)
    return None


def _constraint_term_truth(term: _ConstraintTerm, value: object) -> bool | None:
    if value is _UNKNOWN:
        return None
    try:
        if term.operator == "eq":
            return _literal_equal(cast(StateScalar, value), term.value)
        if term.operator == "ne":
            return not _literal_equal(cast(StateScalar, value), term.value)
        if term.operator == "ge":
            return bool(value >= term.value)  # type: ignore[operator]
        if term.operator == "gt":
            return bool(value > term.value)  # type: ignore[operator]
        if term.operator == "le":
            return bool(value <= term.value)  # type: ignore[operator]
        if term.operator == "lt":
            return bool(value < term.value)  # type: ignore[operator]
    except (TypeError, ValueError):
        return None
    return None


def _values_after_repetitions(
    values: Mapping[str, object],
    deltas: Mapping[str, int | float],
    repetitions: int,
) -> dict[str, object]:
    projected = dict(values)
    for variable_key, delta in deltas.items():
        current = projected.get(variable_key, _UNKNOWN)
        if _is_number(current):
            assert isinstance(current, int | float) and not isinstance(current, bool)
            projected[variable_key] = current + (delta * repetitions)
    return projected


def _traverse_accelerated_loop(
    state: _SearchState,
    acceleration: _ExactLoopAcceleration,
    occurrence_edges: Mapping[str, str],
    lane_by_scene: Mapping[str, str],
    scene_by_node: Mapping[str, str],
    projection: NumericProjection,
    material_edge_ids: set[str],
    prefix_store: _RoutePrefixStore,
) -> _SearchState:
    edge = acceleration.edge
    repetitions = acceleration.repetitions
    values = dict(state.values)
    sources = dict(state.value_sources)
    constraints = state.constraints
    relevant = {item.key for item in projection.relevant_variables}
    for fact in acceleration.effect_facts:
        variable_name = cast(str, fact.attributes["variable"])
        variable_key = identity_from_name(variable_name).key
        if variable_key not in relevant:
            continue
        delta = _numeric_effect_delta(fact)
        current = values.get(variable_key, _UNKNOWN)
        assert delta is not None and _is_number(current)
        assert isinstance(current, int | float) and not isinstance(current, bool)
        values[variable_key] = current + (delta * repetitions)
        prior_source = sources.get(variable_key)
        prior_effect_ids = prior_source.effect_ids if prior_source is not None else ()
        effect_ids = tuple(dict.fromkeys((*prior_effect_ids, fact.id)))
        effect_counts = dict(prior_source.effect_counts) if prior_source is not None else {}
        effect_counts[fact.id] = effect_counts.get(fact.id, 0) + repetitions
        sources[variable_key] = _ValueSource(
            effect_ids,
            tuple((effect_id, effect_counts[effect_id]) for effect_id in effect_ids),
            fact.id,
            (
                prior_source.depends_on_entry_precondition
                if prior_source is not None
                else False
            ),
        )
        constraints = _constraint_with_exact_value(
            constraints,
            variable_key,
            cast(StateScalar, values[variable_key]),
            sources[variable_key].effect_ids,
        )
    persistent = list(state.persistent_lane_ids)
    prefix_id = state.prefix_id
    selected_occurrence = state.selected_occurrence_id
    effect_ids = tuple(dict.fromkeys(item.id for item in acceleration.effect_facts))
    first_record = True
    for _ in range(repetitions):
        for cycle_edge in acceleration.cycle_edges:
            target_scene = scene_by_node.get(cycle_edge.target_id)
            if target_scene is not None:
                lane = lane_by_scene.get(target_scene)
                if lane is not None and lane not in persistent:
                    persistent.append(lane)
            prefix_id = prefix_store.append(
                prefix_id,
                cycle_edge.target_id,
                cycle_edge.id,
                scene_id=target_scene,
                material_edge=cycle_edge.id in material_edge_ids,
                acceleration_group_id=edge.id,
                acceleration_repetitions=(repetitions if first_record else None),
                acceleration_effect_ids=(effect_ids if first_record else ()),
            )
            first_record = False
            selected_occurrence = occurrence_edges.get(
                cycle_edge.id, selected_occurrence
            )
    target_node_id = acceleration.cycle_edges[-1].target_id
    return _SearchState(
        target_node_id,
        values,
        sources,
        state.initial_kinds,
        constraints,
        prefix_id,
        state.requirements,
        state.warnings,
        state.call_stack,
        selected_occurrence,
        tuple(persistent),
        state.loop_count + max(0, repetitions - 1),
        acceleration.suppressed_edge_id,
    )


def _traverse_edge(
    state: _SearchState,
    edge: CanonicalEdge,
    edges: Mapping[str, CanonicalEdge],
    nodes: Mapping[str, CanonicalNode],
    facts: Mapping[str, CanonicalFact],
    occurrence_edges: Mapping[str, str],
    lane_by_scene: Mapping[str, str],
    scene_by_node: Mapping[str, str],
    projection: NumericProjection,
    material_edge_ids: set[str],
    prefix_store: _RoutePrefixStore,
    limits: DeterministicLimitProfile,
) -> tuple[_SearchState | None, tuple[str, ...], str | None]:
    count = prefix_store.transition_count(state.prefix_id, edge.id) + 1
    accelerated_continuation = any(
        state.suppressed_loop_edge_id in member_edges and edge.id in member_edges
        for _repeat_count, member_edges, _effect_ids in prefix_store.acceleration_summaries(
            state.prefix_id
        ).values()
    )
    if count > limits.repetition_per_transition and not accelerated_continuation:
        return None, (), "repetition_per_transition"
    stack = state.call_stack
    call_site = edge.attributes.get("call_site_id")
    if edge.kind in {"call_enter", "call_summary"}:
        if not isinstance(call_site, str) or not call_site:
            return None, (), None
        if len(stack) >= limits.call_depth:
            return None, (), "call_depth"
        stack = (*stack, call_site)
    elif edge.kind == "call_return":
        if call_site is not None:
            if not isinstance(call_site, str):
                return None, (), None
            if stack and stack[-1] == call_site:
                stack = stack[:-1]
            elif not _follows_matching_resumed_summary(
                state, edge, edges, prefix_store
            ):
                return None, (), None

    requirements = list(state.requirements)
    warnings = list(state.warnings)
    constraints = state.constraints
    for fact_id in _strings(edge.attributes.get("gate_ids")):
        fact = facts.get(fact_id)
        if fact is None:
            warnings.append(f"Missing M10 gate fact {fact_id}.")
            continue
        if fact.status == "proven":
            expression = str(fact.attributes.get("original_expression", ""))
            supported_terms = _supported_constraint_terms(expression)
            if supported_terms:
                constraints, contradiction_ids = _intersect_supported_constraints(
                    constraints,
                    supported_terms,
                    fact.id,
                )
                if contradiction_ids:
                    return None, contradiction_ids, None
        outcome, attributions = _evaluate_requirement(
            fact, state.values, state.value_sources, state.initial_kinds
        )
        if outcome is False:
            return None, (fact.id,), None
        requirements.extend(attributions)
        if outcome is None:
            expression = str(fact.attributes.get("original_expression", ""))
            warnings.append(f"Requirement remains unknown: {expression}.")

    values = dict(state.values)
    sources = dict(state.value_sources)
    relevant = {item.key for item in projection.relevant_variables}
    for fact_id in _strings(edge.attributes.get("effect_ids")):
        fact = facts.get(fact_id)
        if fact is not None:
            constraints = _apply_effect(
                fact,
                values,
                sources,
                constraints,
                warnings,
                relevant,
            )
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

    loops = state.loop_count + (1 if count > 1 else 0)
    selected_occurrence = occurrence_edges.get(edge.id, state.selected_occurrence_id)
    persistent = list(state.persistent_lane_ids)
    target_scene = scene_by_node.get(edge.target_id)
    if target_scene is not None:
        lane = lane_by_scene.get(target_scene)
        if lane is not None and lane not in persistent:
            persistent.append(lane)
    prefix_id = prefix_store.append(
        state.prefix_id,
        edge.target_id,
        edge.id,
        scene_id=target_scene,
        material_edge=edge.id in material_edge_ids,
    )
    next_suppressed_loop_edge_id = state.suppressed_loop_edge_id
    if next_suppressed_loop_edge_id is not None:
        suppressed_edge = edges.get(next_suppressed_loop_edge_id)
        if suppressed_edge is None or suppressed_edge.source_id == edge.source_id:
            next_suppressed_loop_edge_id = None
    return (
        _SearchState(
            edge.target_id,
            values,
            sources,
            state.initial_kinds,
            constraints,
            prefix_id,
            tuple(requirements),
            tuple(dict.fromkeys(warnings)),
            stack,
            selected_occurrence,
            tuple(persistent),
            loops,
            next_suppressed_loop_edge_id,
        ),
        (),
        None,
    )


def _resume_call_summary(
    state: _SearchState,
    edge: CanonicalEdge,
    nodes: Mapping[str, CanonicalNode],
    lane_by_scene: Mapping[str, str],
    scene_by_node: Mapping[str, str],
    material_edge_ids: set[str],
    prefix_store: _RoutePrefixStore,
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
    count = prefix_store.transition_count(state.prefix_id, edge.id) + 1
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
    persistent = list(state.persistent_lane_ids)
    target_scene = scene_by_node.get(edge.target_id)
    if target_scene is not None:
        lane = lane_by_scene.get(target_scene)
        if lane is not None and lane not in persistent:
            persistent.append(lane)
    prefix_id = prefix_store.append(
        state.prefix_id,
        edge.target_id,
        edge.id,
        scene_id=target_scene,
        material_edge=edge.id in material_edge_ids,
    )
    return (
        _SearchState(
            edge.target_id,
            dict(state.values),
            dict(state.value_sources),
            state.initial_kinds,
            state.constraints,
            prefix_id,
            state.requirements,
            tuple(dict.fromkeys(warnings)),
            state.call_stack[:-1],
            state.selected_occurrence_id,
            tuple(persistent),
            state.loop_count + (1 if count > 1 else 0),
            None,
        ),
        None,
    )


def _follows_matching_resumed_summary(
    state: _SearchState,
    edge: CanonicalEdge,
    edges: Mapping[str, CanonicalEdge],
    prefix_store: _RoutePrefixStore,
) -> bool:
    """Accept M10's synthetic continuation edge after its frame was popped."""

    previous_edge_id = prefix_store.last_edge_id(state.prefix_id)
    if previous_edge_id is None:
        return False
    previous = edges.get(previous_edge_id)
    return bool(
        previous is not None
        and previous.kind == "call_summary"
        and previous.target_id == edge.source_id
        and previous.attributes.get("call_site_id")
        == edge.attributes.get("call_site_id")
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
    value_sources: Mapping[str, _ValueSource],
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
    value_sources: Mapping[str, _ValueSource],
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
        entry = initial.get(variable.key)
        if source.depends_on_entry_precondition:
            if entry is None or entry.kind is not InitialValueKind.ENTRY_PRECONDITION:
                return RequirementAttribution(
                    fact_id,
                    expression,
                    RequirementSource.UNKNOWN,
                    variable,
                    evidence_ids=evidence,
                )
            return RequirementAttribution(
                fact_id,
                expression,
                RequirementSource.ENTRY_PRECONDITION,
                variable,
                supporting_effect_ids=source.effect_ids,
                supporting_effect_counts=source.effect_counts,
                entry_precondition=entry,
                evidence_ids=evidence,
            )
        if source.repeated_count > 1:
            assert source.last_effect_id is not None
            return RequirementAttribution(
                fact_id,
                expression,
                RequirementSource.REPEATED_EVENT,
                variable,
                repeated_effect_id=source.last_effect_id,
                supporting_effect_ids=source.effect_ids,
                supporting_effect_counts=source.effect_counts,
                repeated_count=source.repeated_count,
                evidence_ids=evidence,
            )
        if source.last_effect_id is None:
            return RequirementAttribution(
                fact_id,
                expression,
                RequirementSource.UNKNOWN,
                variable,
                evidence_ids=evidence,
            )
        return RequirementAttribution(
            fact_id,
            expression,
            RequirementSource.PROVEN_EFFECT,
            variable,
            satisfying_effect_id=source.last_effect_id,
            supporting_effect_ids=source.effect_ids,
            supporting_effect_counts=source.effect_counts,
            evidence_ids=evidence,
        )
    entry = initial.get(variable.key)
    if entry is not None and entry.kind is InitialValueKind.ENTRY_PRECONDITION:
        return RequirementAttribution(
            fact_id,
            expression,
            RequirementSource.ENTRY_PRECONDITION,
            variable,
            entry_precondition=entry,
            evidence_ids=evidence,
        )
    if entry is not None and entry.kind is InitialValueKind.KNOWN:
        return RequirementAttribution(
            fact_id,
            expression,
            RequirementSource.UNKNOWN,
            variable,
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
    sources: dict[str, _ValueSource],
    constraints: _ConstraintState,
    warnings: list[str],
    relevant: set[str],
) -> _ConstraintState:
    variable_name = fact.attributes.get("variable")
    if not isinstance(variable_name, str) or not variable_name:
        if fact.status != "proven":
            warnings.append(f"Effect {fact.id} is unsupported and does not satisfy a gate.")
        return constraints
    variable = identity_from_name(variable_name)
    if variable.key not in relevant:
        return constraints
    if fact.status != "proven":
        values.pop(variable.key, None)
        sources.pop(variable.key, None)
        warnings.append(f"Effect {fact.id} on {variable.key} is not proven.")
        return constraints.without(variable.key)
    operation = str(fact.attributes.get("operation", ""))
    value = fact.attributes.get("value")
    prior_source = sources.get(variable.key)
    if operation == "assignment" and _is_scalar(value):
        values[variable.key] = value
        sources[variable.key] = _ValueSource((fact.id,), ((fact.id, 1),), fact.id)
        constraints = _constraint_with_exact_value(
            constraints,
            variable.key,
            cast(StateScalar, value),
            (fact.id,),
        )
    elif (
        operation in {"increment", "decrement"}
        and isinstance(value, int | float)
        and not isinstance(value, bool)
    ):
        current = values.get(variable.key, _UNKNOWN)
        if isinstance(current, int | float) and not isinstance(current, bool):
            delta = value if operation == "increment" else -value
            values[variable.key] = current + delta
            prior_effect_ids = prior_source.effect_ids if prior_source is not None else ()
            effect_ids = tuple(dict.fromkeys((*prior_effect_ids, fact.id)))
            effect_counts = (
                dict(prior_source.effect_counts) if prior_source is not None else {}
            )
            effect_counts[fact.id] = effect_counts.get(fact.id, 0) + 1
            sources[variable.key] = _ValueSource(
                effect_ids,
                tuple((effect_id, effect_counts[effect_id]) for effect_id in effect_ids),
                fact.id,
                (
                    prior_source.depends_on_entry_precondition
                    if prior_source is not None
                    else False
                ),
            )
            constraints = _constraint_with_exact_value(
                constraints,
                variable.key,
                cast(StateScalar, values[variable.key]),
                sources[variable.key].effect_ids,
            )
        else:
            values.pop(variable.key, None)
            sources.pop(variable.key, None)
            constraints = constraints.without(variable.key)
    else:
        values.pop(variable.key, None)
        sources.pop(variable.key, None)
        constraints = constraints.without(variable.key)
        warnings.append(f"Effect {fact.id} is not a supported literal state transition.")
    return constraints


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
    prefix_store: _RoutePrefixStore,
) -> RouteAlternative:
    node_by_id = {item.id: item for item in graph.nodes}
    edge_by_id = {item.id: item for item in graph.edges}
    evidence_by_id = {item.id: item for item in graph.evidence}
    scene_records = {item.id: item for item in scene_model.scenes}
    node_ids, edge_ids = prefix_store.reconstruct(state.prefix_id)
    transition_counts = prefix_store.transition_counts(state.prefix_id)

    scene_ids: list[str] = []

    def append_scene(scene_id: str | None) -> None:
        if scene_id is not None and (not scene_ids or scene_ids[-1] != scene_id):
            scene_ids.append(scene_id)

    append_scene(scene_by_node.get(node_ids[0]))
    for _edge_id, node_id in zip(edge_ids, node_ids[1:], strict=True):
        append_scene(scene_by_node.get(node_id))
    choice_edges: list[tuple[str, str]] = []
    for edge_id in edge_ids:
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
    satisfying_effect_claims = tuple(
        dict.fromkeys(
            RouteClaim(
                text=f"{item.expression} — supporting effect {effect_id}",
                fact_id=effect_id,
                evidence_ids=tuple(sorted(facts[effect_id].evidence_ids)),
            )
            for item in requirements
            if item.source in {
                RequirementSource.PROVEN_EFFECT,
                RequirementSource.REPEATED_EVENT,
                RequirementSource.ENTRY_PRECONDITION,
            }
            for effect_id in item.supporting_effect_ids
            if effect_id in facts
        )
    )
    warnings = tuple(state.warnings)
    accelerations = prefix_store.acceleration_summaries(state.prefix_id)
    accelerated_counts = {
        group_id: count for group_id, (count, _edges, _effects) in accelerations.items()
    }
    accelerated_member_edges = {
        edge_id for _count, edge_ids, _effects in accelerations.values() for edge_id in edge_ids
    }
    accelerated_effect_ids = {
        fact_id
        for _count, _edge_ids, effect_ids in accelerations.values()
        for fact_id in effect_ids
    }
    edge_repeated_claims = tuple(
        _edge_claim(
            (
                f"Repeat the supported action {accelerated_counts[edge_id]} proven time(s)."
                if edge_id in accelerated_counts
                else f"Repeat the supported action {count - 1} additional time(s)."
            ),
            edge_by_id[edge_id],
            node_by_id,
            repeated_count=(
                accelerated_counts[edge_id]
                if edge_id in accelerated_counts
                else count - 1
            ),
        )
        for edge_id, count in sorted(transition_counts.items())
        if count > 1
        and (edge_id not in accelerated_member_edges or edge_id in accelerated_counts)
    )
    requirement_repeated_claims = tuple(
        RouteClaim(
            text=(
                f"Apply contributing effect {effect_id} {count} proven time(s); "
                "the entry assumption is still required."
                if item.source is RequirementSource.ENTRY_PRECONDITION
                else f"Apply effect {effect_id} {count} proven time(s)."
            ),
            fact_id=effect_id,
            evidence_ids=tuple(sorted(facts[effect_id].evidence_ids)),
            repeated_count=count,
        )
        for item in requirements
        for effect_id, count in item.supporting_effect_counts
        if count > 1 and effect_id in facts and effect_id not in accelerated_effect_ids
    )
    repeated_claims = (*edge_repeated_claims, *requirement_repeated_claims)
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
        _warning_claim(warning, node_ids, edge_ids, graph, facts)
        for warning in warnings
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
                        for node_id in node_ids
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
                        for node_id in node_ids
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
        len(_entry_preconditions(requirements)),
        len(persistent),
        state.loop_count,
        len(scene_ids),
        len(edge_ids),
        "|".join(edge_ids),
    )
    instructions = _instructions(
        scene_claims,
        choice_claims,
        requirements,
        repeated_claims,
        persistent_claims,
        warning_claims,
    )
    call_contexts = _call_contexts(edge_ids, graph, scene_model)
    selected_occurrence = next(
        (
            item
            for item in scene_model.occurrences
            if item.id == state.selected_occurrence_id
        ),
        None,
    )
    fact_id_values = {item.fact_id for item in requirements}
    fact_id_values.update(
        effect_id
        for item in requirements
        for effect_id in item.supporting_effect_ids
    )
    if selected_occurrence is not None:
        fact_id_values.update(selected_occurrence.guard_fact_ids)
        fact_id_values.update(selected_occurrence.provenance.fact_ids)
    fact_ids = tuple(sorted(fact_id_values))
    evidence_ids: set[str] = set()
    proof_ids: set[str] = set()
    for node_id in node_ids:
        evidence_ids.update(node_by_id[node_id].evidence_ids)
        proof_ids.update(node_by_id[node_id].proof_ids)
    for edge_id in edge_ids:
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
        node_ids,
        edge_ids,
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
            node_ids=tuple(sorted(set(node_ids))),
            edge_ids=tuple(
                sorted(
                    set(edge_ids)
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
        satisfying_effect_claims,
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
    for entry, fact_id, evidence_ids in _entry_preconditions(requirements):
        rows.append({
            "kind": "starting_assumption",
            "text": (
                f"Start with {entry.variable.key} = "
                f"{json.dumps(entry.value, ensure_ascii=False, sort_keys=True)}."
            ),
            "fact_id": fact_id,
            "evidence_ids": evidence_ids,
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
            "fact_id": claim.fact_id,
            "evidence_ids": claim.evidence_ids,
            "proof_ids": claim.proof_ids,
        })
    for requirement in requirements:
        source = {
            RequirementSource.PROVEN_EFFECT: "an earlier proven effect",
            RequirementSource.REPEATED_EVENT: "a proven repeated-event count",
            RequirementSource.ENTRY_PRECONDITION: (
                "the explicit starting assumption plus earlier proven effects"
                if requirement.supporting_effect_ids
                else "the explicit starting assumption"
            ),
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
    node_ids: Sequence[str],
    edge_ids: Sequence[str],
    graph: CanonicalGraph,
    facts: Mapping[str, CanonicalFact],
) -> RouteClaim:
    edges = {item.id: item for item in graph.edges}
    nodes = {item.id: item for item in graph.nodes}
    for edge_id in edge_ids:
        edge = edges[edge_id]
        gate_ids = _strings(edge.attributes.get("gate_ids"))
        if edge_id in warning or any(fact_id in warning for fact_id in gate_ids):
            return _edge_claim(warning, edge, nodes)
    for node_id in node_ids:
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
) -> tuple[object, ...]:
    requirements = tuple(
        (
            item.fact_id,
            item.source.value,
            item.satisfying_effect_id,
            item.repeated_effect_id,
            item.supporting_effect_ids,
            item.supporting_effect_counts,
            item.repeated_count,
        )
        for item in _dedupe_requirements(state.requirements)
    )
    return (
        state.node_id,
        state.call_stack,
        projection.key_for(state.values),
        state.constraints.normalized_key(),
        tuple(
            (
                key,
                state.values.get(key, "unknown"),
                state.value_sources[key].effect_ids,
                state.value_sources[key].effect_counts,
                state.value_sources[key].last_effect_id,
                state.value_sources[key].depends_on_entry_precondition,
            )
            for key in sorted(state.value_sources)
            if key in {item.key for item in projection.relevant_variables}
        ),
        requirements,
        state.warnings,
        state.persistent_lane_ids,
        state.selected_occurrence_id,
        state.suppressed_loop_edge_id,
    )


def _material_prefix_signature(
    state: _SearchState,
    prefix_store: _RoutePrefixStore,
) -> _MaterialPrefixSignature:
    """Identify route-visible diversity separately from semantic dominance."""

    prefix = prefix_store.record(state.prefix_id)
    return (
        prefix.scene_signature_id,
        prefix.material_edge_signature_id,
    )


def _partial_rank(
    state: _SearchState,
    prefix_store: _RoutePrefixStore,
    minimum_persistent_commitments: int,
) -> tuple[int | str, ...]:
    prefix = prefix_store.record(state.prefix_id)
    requirements = _dedupe_requirements(state.requirements)
    return (
        len(state.warnings),
        sum(item.source is RequirementSource.UNKNOWN for item in requirements),
        len(_entry_preconditions(requirements)),
        max(len(state.persistent_lane_ids), minimum_persistent_commitments),
        state.loop_count,
        prefix.scene_count,
        prefix.edge_count,
        state.prefix_id,
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
        + len(state.requirements)
        + len(state.call_stack)
        + (1 if state.suppressed_loop_edge_id is not None else 0)
        + sum(
            1
            + len(item.equality)
            + len(item.equality_fact_ids)
            + len(item.exclusions)
            + (1 if item.lower is not None else 0)
            + (1 if item.upper is not None else 0)
            for item in state.constraints.variables
        )
        + sum(len(source.effect_ids) for source in state.value_sources.values())
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


def _call_resume_predecessors(
    edges: Sequence[CanonicalEdge],
) -> dict[str, tuple[str, ...]]:
    """Bind each call summary continuation to its callee's exact return boundary."""

    outgoing: dict[str, list[CanonicalEdge]] = defaultdict(list)
    enters_by_site: dict[str, list[CanonicalEdge]] = defaultdict(list)
    summaries_by_site: dict[str, list[CanonicalEdge]] = defaultdict(list)
    for edge in edges:
        outgoing[edge.source_id].append(edge)
        call_site = edge.attributes.get("call_site_id")
        if not isinstance(call_site, str) or not call_site:
            continue
        if edge.kind == "call_enter":
            enters_by_site[call_site].append(edge)
        elif edge.kind == "call_summary":
            summaries_by_site[call_site].append(edge)
    for records in outgoing.values():
        records.sort(key=lambda item: item.id)

    result: dict[str, set[str]] = defaultdict(set)
    for call_site in sorted(set(enters_by_site) & set(summaries_by_site)):
        exits: set[str] = set()
        for enter in sorted(enters_by_site[call_site], key=lambda item: item.id):
            pending = deque([enter.target_id])
            seen = {enter.target_id}
            while pending:
                node_id = pending.popleft()
                node_edges = outgoing.get(node_id, ())
                nested_sites = {
                    nested_site
                    for edge in node_edges
                    if edge.kind == "call_enter"
                    and isinstance(
                        nested_site := edge.attributes.get("call_site_id"), str
                    )
                    and nested_site
                }
                for edge in node_edges:
                    edge_site = edge.attributes.get("call_site_id")
                    if edge.kind == "call_return" and edge_site is None:
                        exits.add(edge.target_id)
                        continue
                    if edge.kind == "call_enter" and edge_site in nested_sites:
                        continue
                    if edge.target_id not in seen:
                        seen.add(edge.target_id)
                        pending.append(edge.target_id)
        for summary in summaries_by_site[call_site]:
            result[summary.target_id].update(exits)
    return {key: tuple(sorted(values)) for key, values in sorted(result.items())}


def _matches_target_entry_context(
    edge: CanonicalEdge, anchors: Sequence[_TargetAnchor]
) -> bool:
    matching = [item for item in anchors if item.node_id == edge.target_id]
    if not matching:
        return True
    return any(
        item.required_edge_id is None or item.required_edge_id == edge.id for item in matching
    )


def _resolved_reverse_nodes(
    targets: set[str],
    incoming: Mapping[str, Sequence[CanonicalEdge]],
    *,
    resume_predecessors: Mapping[str, Sequence[str]] | None = None,
) -> set[str]:
    result = set(targets)
    pending = deque(sorted(targets))
    while pending:
        node_id = pending.popleft()
        for edge in incoming.get(node_id, ()):
            if edge.resolved and edge.source_id not in result:
                result.add(edge.source_id)
                pending.append(edge.source_id)
        for predecessor in (resume_predecessors or {}).get(node_id, ()):
            if predecessor not in result:
                result.add(predecessor)
                pending.append(predecessor)
    return result


def _reverse_nodes(
    targets: set[str],
    incoming: Mapping[str, Sequence[CanonicalEdge]],
    *,
    resume_predecessors: Mapping[str, Sequence[str]] | None = None,
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
        for predecessor in (resume_predecessors or {}).get(node_id, ()):
            if predecessor not in result:
                result.add(predecessor)
                pending.append(predecessor)
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
    result: list[RequirementAttribution] = []
    seen: set[RequirementAttribution] = set()
    for item in requirements:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _entry_preconditions(
    requirements: Iterable[RequirementAttribution],
) -> tuple[tuple[InitialStateValue, str, tuple[str, ...]], ...]:
    result: list[tuple[InitialStateValue, str, tuple[str, ...]]] = []
    seen: set[InitialStateValue] = set()
    for item in requirements:
        entry = item.entry_precondition
        if entry is None or entry in seen:
            continue
        seen.add(entry)
        result.append((entry, item.fact_id, item.evidence_ids))
    return tuple(result)


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in value):
        return ()
    return tuple(value)


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bool)
