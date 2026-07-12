"""Deterministic interprocedural control regions and route semantics.

The M01 graph intentionally contains convenient return-to-continuation edges.  Those
edges form a cross product when a procedure has multiple callers.  This module treats
them as legacy evidence only and builds a normalized graph with a private return site
for every call.  No creator expression is evaluated and no target is guessed.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from renpy_story_mapper.state import FactStatus, Requirement, StateEffect

CONTROL_FLOW_SCHEMA_VERSION = 1
VIRTUAL_EXIT_ID = "__control_virtual_super_exit__"


class FlowEdgeRole(StrEnum):
    ENTRY = "entry"
    FLOW = "flow"
    CHOICE = "choice"
    CONDITION = "condition"
    CALL_ENTER = "call_enter"
    CALL_RETURN = "call_return"
    CALL_SUMMARY = "call_summary"
    JUMP = "jump"
    LOOP_BODY = "loop_body"
    LOOP_BACK = "loop_back"
    LOOP_EXIT = "loop_exit"
    TERMINAL = "terminal"
    UNRESOLVED = "unresolved"


class RouteClassification(StrEnum):
    LOCAL_DETOUR = "local_detour"
    OPTIONAL_DETOUR = "optional_detour"
    RECONVERGENT_ROUTE_SEGMENT = "reconvergent_route_segment"
    PERSISTENT_ROUTE = "persistent_route"
    TERMINAL_SPLIT = "terminal_split"
    LOOP_CHOICE = "loop_choice"
    UNRESOLVED = "unresolved"


def _stable_id(prefix: str, *values: str) -> str:
    digest = hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True, order=True)
class ControlNode:
    id: str
    kind: str
    label: str
    hidden: bool = False
    synthetic: bool = False
    source: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "hidden": self.hidden,
            "synthetic": self.synthetic,
        }
        if self.source is not None:
            value["source"] = dict(self.source)
        return value


@dataclass(frozen=True)
class ControlEdge:
    id: str
    source: str
    target: str
    role: FlowEdgeRole
    semantic_roles: tuple[str, ...]
    evidence: tuple[Mapping[str, object], ...]
    call_site_id: str | None = None
    resolved: bool = True

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "role": self.role.value,
            "semantic_roles": list(self.semantic_roles),
            "evidence": [dict(item) for item in self.evidence],
            "resolved": self.resolved,
        }
        if self.call_site_id is not None:
            value["call_site_id"] = self.call_site_id
        return value


@dataclass(frozen=True, order=True)
class ProcedureSummary:
    id: str
    label: str
    entry_node_id: str
    return_node_ids: tuple[str, ...]
    call_site_ids: tuple[str, ...]
    may_return: bool
    may_terminate: bool
    recursive: bool
    looping: bool
    unresolved: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "entry_node_id": self.entry_node_id,
            "return_node_ids": list(self.return_node_ids),
            "call_site_ids": list(self.call_site_ids),
            "may_return": self.may_return,
            "may_terminate": self.may_terminate,
            "recursive": self.recursive,
            "looping": self.looping,
            "unresolved": self.unresolved,
        }


@dataclass(frozen=True, order=True)
class LoopSummary:
    id: str
    node_ids: tuple[str, ...]
    entry_node_ids: tuple[str, ...]
    exit_edge_ids: tuple[str, ...]
    back_edge_ids: tuple[str, ...]
    self_loop: bool
    irreducible: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "node_ids": list(self.node_ids),
            "entry_node_ids": list(self.entry_node_ids),
            "exit_edge_ids": list(self.exit_edge_ids),
            "back_edge_ids": list(self.back_edge_ids),
            "self_loop": self.self_loop,
            "irreducible": self.irreducible,
        }


@dataclass(frozen=True, order=True)
class StateRead:
    variable: str
    expression: str
    node_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "variable": self.variable,
            "expression": self.expression,
            "node_id": self.node_id,
        }


@dataclass(frozen=True, order=True)
class StateWrite:
    variable: str
    value_key: str
    expression: str
    node_id: str
    value: object

    def to_dict(self) -> dict[str, object]:
        return {
            "variable": self.variable,
            "value": self.value,
            "expression": self.expression,
            "node_id": self.node_id,
        }


@dataclass(frozen=True, order=True)
class ControlArm:
    id: str
    region_id: str
    ordinal: int
    entry_node_id: str
    edge_id: str
    node_ids: tuple[str, ...]
    terminal_node_ids: tuple[str, ...]
    unresolved: bool
    state_reads: tuple[StateRead, ...] = ()
    state_writes: tuple[StateWrite, ...] = ()
    terminal_summary: str = "none"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "region_id": self.region_id,
            "ordinal": self.ordinal,
            "entry_node_id": self.entry_node_id,
            "edge_id": self.edge_id,
            "node_ids": list(self.node_ids),
            "terminal_node_ids": list(self.terminal_node_ids),
            "unresolved": self.unresolved,
            "state_reads": [item.to_dict() for item in self.state_reads],
            "state_writes": [item.to_dict() for item in self.state_writes],
            "terminal_summary": self.terminal_summary,
        }


@dataclass(frozen=True, order=True)
class ControlRegion:
    id: str
    split_node_id: str
    merge_node_id: str | None
    classification: RouteClassification
    arm_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    parent_region_id: str | None
    single_entry: bool
    single_exit: bool
    persistence_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "split_node_id": self.split_node_id,
            "merge_node_id": self.merge_node_id,
            "classification": self.classification.value,
            "arm_ids": list(self.arm_ids),
            "node_ids": list(self.node_ids),
            "parent_region_id": self.parent_region_id,
            "single_entry": self.single_entry,
            "single_exit": self.single_exit,
            "persistence_reasons": list(self.persistence_reasons),
        }


@dataclass(frozen=True, order=True)
class ControlOwnership:
    node_id: str
    region_id: str
    arm_id: str | None

    def to_dict(self) -> dict[str, object]:
        return {"node_id": self.node_id, "region_id": self.region_id, "arm_id": self.arm_id}


@dataclass(frozen=True, order=True)
class ControlDiagnostic:
    id: str
    kind: str
    node_ids: tuple[str, ...]
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "node_ids": list(self.node_ids),
            "message": self.message,
        }


@dataclass(frozen=True)
class _ReachabilitySummary:
    terminal_node_ids: tuple[str, ...]
    terminal_summary: str
    unresolved: bool


@dataclass(frozen=True)
class ControlFlowAnalysis:
    nodes: tuple[ControlNode, ...]
    edges: tuple[ControlEdge, ...]
    procedures: tuple[ProcedureSummary, ...]
    loops: tuple[LoopSummary, ...]
    arms: tuple[ControlArm, ...]
    regions: tuple[ControlRegion, ...]
    ownership: tuple[ControlOwnership, ...]
    immediate_post_dominators: tuple[tuple[str, str | None], ...]
    terminals: tuple[tuple[str, str], ...]
    diagnostics: tuple[ControlDiagnostic, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": CONTROL_FLOW_SCHEMA_VERSION,
            "virtual_exit_id": VIRTUAL_EXIT_ID,
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "procedures": [item.to_dict() for item in self.procedures],
            "loops": [item.to_dict() for item in self.loops],
            "arms": [item.to_dict() for item in self.arms],
            "regions": [item.to_dict() for item in self.regions],
            "ownership": [item.to_dict() for item in self.ownership],
            "immediate_post_dominators": [
                {"node_id": node, "post_dominator_id": parent}
                for node, parent in self.immediate_post_dominators
            ],
            "terminals": [{"node_id": node, "kind": kind} for node, kind in self.terminals],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }

    def canonical_json(self) -> bytes:
        return _canonical(self.to_dict())


@dataclass(frozen=True)
class StoryQuotientEdge:
    id: str
    source_id: str
    target_id: str
    semantic_roles: tuple[str, ...]
    transition_evidence: tuple[Mapping[str, object], ...]
    control_edge_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "semantic_roles": list(self.semantic_roles),
            "transition_evidence": [dict(item) for item in self.transition_evidence],
            "control_edge_ids": list(self.control_edge_ids),
        }


def analyze_control_flow(
    graph: Mapping[str, object],
    semantic_story: Mapping[str, object],
    gates: object = (),
    effects: object = (),
) -> ControlFlowAnalysis:
    """Build deterministic call, loop, post-dominator, and control-region facts."""

    raw_nodes = _read_records(graph.get("nodes"), "graph.nodes")
    raw_edges = _read_records(graph.get("edges"), "graph.edges")
    _validate_semantic_story(semantic_story)
    node_by_id = {_string(item, "id"): item for item in raw_nodes}
    if len(node_by_id) != len(raw_nodes):
        raise ValueError("graph.nodes contains duplicate ids")
    labels = {
        _metadata_string(node, "name"): node_id
        for node_id, node in node_by_id.items()
        if node.get("kind") == "label"
    }
    by_source = _index_raw_edges(raw_edges, node_by_id)
    procedures = _procedure_summaries(node_by_id, raw_edges, labels, by_source)
    procedure_by_label = {item.label: item for item in procedures}
    nodes, edges = _normalize_graph(node_by_id, raw_edges, procedure_by_label, by_source)
    adjacency = _adjacency(nodes, edges)
    terminals = _terminals(nodes, edges, procedures, raw_edges)
    loops, edges = _loops(nodes, edges, adjacency)
    adjacency = _adjacency(nodes, edges)
    ipdom, postdom_diagnostics = _post_dominators(nodes, adjacency, {item[0] for item in terminals})
    reachability = (
        _reachability_summaries(nodes, adjacency, terminals)
        if any(node.kind in {"if", "menu"} for node in nodes)
        else {}
    )
    state_reads, state_writes = _state_lineage_facts(gates, effects, nodes)
    arms, regions = _regions(
        nodes,
        edges,
        adjacency,
        terminals,
        loops,
        ipdom,
        state_reads,
        state_writes,
        reachability,
    )
    regions = _region_parents(regions, arms)
    ownership = _ownership(arms, regions)
    diagnostics = [*postdom_diagnostics]
    for loop in loops:
        if loop.irreducible:
            diagnostics.append(
                ControlDiagnostic(
                    _stable_id("diag", "irreducible_loop", loop.id),
                    "irreducible_loop",
                    loop.node_ids,
                    "Multi-entry SCC is unstructured; no natural back-edge is asserted.",
                )
            )
    for procedure in procedures:
        if procedure.unresolved:
            diagnostics.append(
                ControlDiagnostic(
                    _stable_id("diag", "procedure_unresolved", procedure.label),
                    "procedure_unresolved",
                    (procedure.entry_node_id,),
                    f"Procedure {procedure.label!r} contains unresolved control flow.",
                )
            )
    return ControlFlowAnalysis(
        tuple(sorted(nodes, key=lambda item: item.id)),
        tuple(sorted(edges, key=lambda item: item.id)),
        tuple(sorted(procedures, key=lambda item: item.label)),
        tuple(sorted(loops, key=lambda item: item.id)),
        tuple(sorted(arms, key=lambda item: (item.region_id, item.ordinal))),
        tuple(sorted(regions, key=lambda item: item.id)),
        tuple(sorted(ownership, key=lambda item: (item.node_id, item.region_id))),
        tuple(sorted((node, parent) for node, parent in ipdom.items() if node != VIRTUAL_EXIT_ID)),
        tuple(sorted(terminals)),
        tuple(sorted(diagnostics)),
    )


def derive_story_quotient(
    analysis: ControlFlowAnalysis,
    node_to_story: Mapping[str, str],
) -> tuple[StoryQuotientEdge, ...]:
    """Collapse nodes while retaining every ordered evidence item and semantic role.

    There is deliberately no ``kind`` field: consumers must inspect ``semantic_roles``.
    """

    grouped: dict[tuple[str, str], list[ControlEdge]] = defaultdict(list)
    for edge in analysis.edges:
        source = node_to_story.get(edge.source)
        target = node_to_story.get(edge.target)
        if source is None or target is None or source == target:
            continue
        grouped[(source, target)].append(edge)
    result: list[StoryQuotientEdge] = []
    for (source, target), group in sorted(grouped.items()):
        ordered = sorted(group, key=lambda item: item.id)
        roles = tuple(sorted({role for edge in ordered for role in edge.semantic_roles}))
        evidence = tuple(item for edge in ordered for item in edge.evidence)
        edge_ids = tuple(edge.id for edge in ordered)
        result.append(
            StoryQuotientEdge(
                _stable_id("quotient", source, target, *edge_ids),
                source,
                target,
                roles,
                evidence,
                edge_ids,
            )
        )
    return tuple(result)


def _read_records(value: object, name: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{name} must be a list of objects")
    return [dict(item) for item in value]


def _string(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        raise ValueError(f"record {key} must be a string")
    return value


def _metadata_string(record: Mapping[str, object], key: str) -> str:
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping) or not isinstance(metadata.get(key), str):
        raise ValueError(f"node metadata.{key} must be a string")
    return str(metadata[key])


def _validate_semantic_story(story: Mapping[str, object]) -> None:
    if story.get("schema_version") != 1:
        raise ValueError("semantic_story schema_version must be 1")
    _read_records(story.get("transitions"), "semantic_story.transitions")


def _index_raw_edges(
    edges: Sequence[Mapping[str, object]], node_by_id: Mapping[str, Mapping[str, object]]
) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = defaultdict(list)
    for edge in edges:
        source, target = _string(edge, "source"), _string(edge, "target")
        if source not in node_by_id or target not in node_by_id:
            raise ValueError("graph edge references an unknown node")
        result[source].append(dict(edge))
    for values in result.values():
        values.sort(key=_raw_edge_key)
    return result


def _raw_edge_key(edge: Mapping[str, object]) -> tuple[str, str, str, str]:
    return (
        _string(edge, "source"),
        _string(edge, "target"),
        _string(edge, "kind"),
        _canonical(edge.get("metadata")).decode(),
    )


def _procedure_summaries(
    nodes: Mapping[str, Mapping[str, object]],
    edges: Sequence[Mapping[str, object]],
    labels: Mapping[str, str],
    outgoing: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[ProcedureSummary]:
    call_targets: dict[str, set[str]] = defaultdict(set)
    callers: dict[str, set[str]] = defaultdict(set)
    unresolved_labels: set[str] = set()
    for edge in edges:
        source = _string(edge, "source")
        kind = _string(edge, "kind")
        source_label = str(nodes[source].get("label", ""))
        if kind == "call" and nodes[_string(edge, "target")].get("kind") == "label":
            target_label = str(nodes[_string(edge, "target")].get("label", ""))
            call_targets[source_label].add(target_label)
            callers[target_label].add(source)
        if "unresolved" in kind or kind.startswith(("dynamic_", "missing_")):
            unresolved_labels.add(source_label)
    components = _tarjan({label: tuple(sorted(call_targets[label])) for label in labels})
    recursive = {
        label
        for component in components
        if len(component) > 1 or any(label in call_targets[label] for label in component)
        for label in component
    }
    returns = {
        label: tuple(
            sorted(
                node_id
                for node_id, node in nodes.items()
                if node.get("kind") == "return" and node.get("label") == label
            )
        )
        for label in labels
    }
    # Start pessimistic: a return after a non-returning recursive call is unreachable.
    may_return = dict.fromkeys(labels, False)
    # Tail jumps and calls followed by reachable returns are fixed-point facts.
    changed = True
    while changed:
        changed = False
        for label, entry in sorted(labels.items()):
            if may_return[label]:
                continue
            if _procedure_reaches(
                entry,
                label,
                nodes,
                outgoing,
                may_return,
                {},
                "return",
            ):
                may_return[label] = True
                changed = True
    may_terminate = dict.fromkeys(labels, False)
    changed = True
    while changed:
        changed = False
        for label, entry in sorted(labels.items()):
            if may_terminate[label]:
                continue
            if _procedure_reaches(
                entry,
                label,
                nodes,
                outgoing,
                may_return,
                may_terminate,
                "terminate",
            ):
                may_terminate[label] = True
                changed = True
    looping = {
        label: label in recursive or _procedure_has_local_cycle(entry, label, nodes, outgoing)
        for label, entry in labels.items()
    }
    return [
        ProcedureSummary(
            _stable_id("procedure", label, labels[label]),
            label,
            labels[label],
            returns[label],
            tuple(sorted(callers[label])),
            may_return[label],
            may_terminate[label],
            label in recursive,
            looping[label],
            label in unresolved_labels,
        )
        for label in sorted(labels)
    ]


def _procedure_reaches(
    entry: str,
    label: str,
    nodes: Mapping[str, Mapping[str, object]],
    outgoing: Mapping[str, Sequence[Mapping[str, object]]],
    may_return: Mapping[str, bool],
    may_terminate: Mapping[str, bool],
    goal: str,
) -> bool:
    pending, seen = [entry], set()
    while pending:
        node_id = pending.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        node = nodes[node_id]
        if goal == "return" and node.get("kind") == "return":
            return True
        if goal == "terminate" and node.get("kind") == "module_end":
            return True
        for edge in outgoing.get(node_id, ()):
            kind, target = _string(edge, "kind"), _string(edge, "target")
            if kind == "return":
                continue
            if kind == "call":
                continue
            if kind == "call_continuation":
                call = next(
                    (item for item in outgoing[node_id] if _string(item, "kind") == "call"), None
                )
                if call is None:
                    continue
                called = str(nodes[_string(call, "target")].get("label", ""))
                if goal == "terminate" and may_terminate.get(called, False):
                    return True
                if not may_return.get(called, False):
                    continue
            target_label = str(nodes[target].get("label", ""))
            if kind == "jump" and target_label != label:
                target_summary = (
                    may_return.get(target_label, False)
                    if goal == "return"
                    else may_terminate.get(target_label, False)
                )
                if target_summary:
                    return True
                continue
            if target_label == label or nodes[target].get("kind") in {
                "module_end",
                "unresolved",
                "scope_boundary",
            }:
                pending.append(target)
    return False


def _procedure_has_local_cycle(
    entry: str,
    label: str,
    nodes: Mapping[str, Mapping[str, object]],
    outgoing: Mapping[str, Sequence[Mapping[str, object]]],
) -> bool:
    adjacency: dict[str, tuple[str, ...]] = {}
    reachable = _reachable_ids(entry, outgoing)
    for node_id in reachable:
        if nodes[node_id].get("label") != label:
            continue
        adjacency[node_id] = tuple(
            _string(edge, "target")
            for edge in outgoing.get(node_id, ())
            if _string(edge, "kind") not in {"call", "return"}
            and nodes[_string(edge, "target")].get("label") == label
        )
    return any(
        len(component) > 1 or any(node in adjacency.get(node, ()) for node in component)
        for component in _tarjan(adjacency)
    )


def _reachable_ids(entry: str, outgoing: Mapping[str, Sequence[Mapping[str, object]]]) -> set[str]:
    pending, seen = [entry], set()
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        pending.extend(_string(edge, "target") for edge in outgoing.get(node, ()))
    return seen


def _normalize_graph(
    raw_nodes: Mapping[str, Mapping[str, object]],
    raw_edges: Sequence[Mapping[str, object]],
    procedures: Mapping[str, ProcedureSummary],
    outgoing: Mapping[str, Sequence[Mapping[str, object]]],
) -> tuple[list[ControlNode], list[ControlEdge]]:
    nodes = [
        ControlNode(
            node_id,
            str(node.get("kind", "unknown")),
            str(node.get("label", "")),
            hidden=node.get("kind") == "merge",
            source=_mapping_or_none(node.get("source")),
        )
        for node_id, node in raw_nodes.items()
    ]
    result: list[ControlEdge] = []
    for raw in sorted(raw_edges, key=_raw_edge_key):
        kind = _string(raw, "kind")
        if kind in {"call", "call_continuation", "return"}:
            continue
        result.append(
            _control_edge(
                _string(raw, "source"), _string(raw, "target"), _base_role(kind), (kind,), (raw,)
            )
        )
    for procedure in sorted(procedures.values(), key=lambda item: item.label):
        if not procedure.call_site_ids or not procedure.return_node_ids:
            continue
        procedure_exit = _stable_id("procedure_exit", procedure.id)
        nodes.append(
            ControlNode(
                procedure_exit,
                "procedure_return_boundary",
                procedure.label,
                hidden=True,
                synthetic=True,
            )
        )
        for return_node in procedure.return_node_ids:
            result.append(
                _control_edge(
                    return_node,
                    procedure_exit,
                    FlowEdgeRole.CALL_RETURN,
                    ("procedure_return",),
                    (),
                    resolved=True,
                )
            )
    for call_id, call_node in sorted(raw_nodes.items()):
        if call_node.get("kind") != "call":
            continue
        call_edges = [
            edge
            for edge in outgoing.get(call_id, ())
            if _string(edge, "kind")
            in {"call", "dynamic_call", "missing_call", "call_out_of_scope"}
        ]
        continuations = [
            edge
            for edge in outgoing.get(call_id, ())
            if _string(edge, "kind") == "call_continuation"
        ]
        if not continuations:
            continue
        continuation = continuations[0]
        known_call = next((edge for edge in call_edges if _string(edge, "kind") == "call"), None)
        resolved = known_call is not None
        if call_edges:
            enter = call_edges[0]
            result.append(
                _control_edge(
                    call_id,
                    _string(enter, "target"),
                    FlowEdgeRole.CALL_ENTER,
                    ("call_enter",),
                    (enter,),
                    call_id,
                    resolved,
                )
            )
        called_summary: ProcedureSummary | None = None
        if known_call is not None:
            called_label = str(raw_nodes[_string(known_call, "target")].get("label", ""))
            called_summary = procedures.get(called_label)
        if called_summary is None or called_summary.may_return:
            return_site = _stable_id("return_site", call_id)
            nodes.append(
                ControlNode(
                    return_site,
                    "call_return_site",
                    str(call_node.get("label", "")),
                    hidden=True,
                    synthetic=True,
                )
            )
            evidence = (*tuple(call_edges[:1]), continuation)
            result.append(
                _control_edge(
                    call_id,
                    return_site,
                    FlowEdgeRole.CALL_SUMMARY,
                    ("call_summary",),
                    evidence,
                    call_id,
                    resolved,
                )
            )
            result.append(
                _control_edge(
                    return_site,
                    _string(continuation, "target"),
                    FlowEdgeRole.CALL_RETURN,
                    ("call_return",),
                    (continuation,),
                    call_id,
                    resolved,
                )
            )
    return nodes, result


def _base_role(kind: str) -> FlowEdgeRole:
    if kind == "label_entry":
        return FlowEdgeRole.ENTRY
    if kind in {"menu_choice", "menu_no_choice", "choice_body"}:
        return FlowEdgeRole.CHOICE
    if kind in {"condition", "condition_false", "branch_body"}:
        return FlowEdgeRole.CONDITION
    if "jump" in kind:
        return FlowEdgeRole.UNRESOLVED if kind != "jump" else FlowEdgeRole.JUMP
    if "unresolved" in kind or kind.startswith(("dynamic_", "missing_")) or "out_of_scope" in kind:
        return FlowEdgeRole.UNRESOLVED
    return FlowEdgeRole.FLOW


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return {str(key): item for key, item in value.items()}
    return None


def _control_edge(
    source: str,
    target: str,
    role: FlowEdgeRole,
    semantic_roles: tuple[str, ...],
    evidence: Iterable[Mapping[str, object]],
    call_site: str | None = None,
    resolved: bool = True,
) -> ControlEdge:
    evidence_tuple = tuple(dict(item) for item in evidence)
    identity = _canonical(
        [source, target, role.value, semantic_roles, evidence_tuple, call_site]
    ).decode()
    return ControlEdge(
        _stable_id("flow", identity),
        source,
        target,
        role,
        semantic_roles,
        evidence_tuple,
        call_site,
        resolved,
    )


def _adjacency(
    nodes: Sequence[ControlNode], edges: Sequence[ControlEdge]
) -> dict[str, tuple[str, ...]]:
    values: dict[str, list[str]] = {node.id: [] for node in nodes}
    for edge in edges:
        if edge.role != FlowEdgeRole.CALL_ENTER:
            values[edge.source].append(edge.target)
    return {node: tuple(sorted(set(targets))) for node, targets in values.items()}


def _terminals(
    nodes: Sequence[ControlNode],
    edges: Sequence[ControlEdge],
    procedures: Sequence[ProcedureSummary],
    raw_edges: Sequence[Mapping[str, object]],
) -> list[tuple[str, str]]:
    called = {item.label for item in procedures if item.call_site_ids}
    outgoing = defaultdict(list)
    for edge in edges:
        if edge.role != FlowEdgeRole.CALL_ENTER:
            outgoing[edge.source].append(edge)
    raw_return_sources = {
        _string(edge, "source") for edge in raw_edges if _string(edge, "kind") == "return"
    }
    result: dict[str, str] = {}
    for node in nodes:
        if node.kind == "module_end":
            result[node.id] = "module_end"
        elif node.kind in {"unresolved", "scope_boundary"}:
            result[node.id] = "unresolved"
        elif node.id in raw_return_sources and node.label not in called:
            result[node.id] = "return"
        elif node.kind == "procedure_return_boundary":
            result[node.id] = "procedure_return_boundary"
        elif not outgoing[node.id] and node.kind != "call_return_site":
            result[node.id] = "non_returning_call" if node.kind == "call" else "dead_end"
    return sorted(result.items())


def _tarjan(adjacency: Mapping[str, Sequence[str]]) -> list[tuple[str, ...]]:
    index = 0
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    component_stack: list[str] = []
    on_stack: set[str] = set()
    result: list[tuple[str, ...]] = []
    for root in sorted(adjacency):
        if root in indices:
            continue
        indices[root] = low[root] = index
        index += 1
        component_stack.append(root)
        on_stack.add(root)
        # Frames are node, next-successor offset, and DFS parent.
        frames: list[tuple[str, int, str | None]] = [(root, 0, None)]
        while frames:
            node, offset, parent = frames[-1]
            targets = adjacency.get(node, ())
            if offset < len(targets):
                target = targets[offset]
                frames[-1] = (node, offset + 1, parent)
                if target not in indices:
                    indices[target] = low[target] = index
                    index += 1
                    component_stack.append(target)
                    on_stack.add(target)
                    frames.append((target, 0, node))
                elif target in on_stack:
                    low[node] = min(low[node], indices[target])
                continue
            frames.pop()
            if parent is not None:
                low[parent] = min(low[parent], low[node])
            if low[node] != indices[node]:
                continue
            component: list[str] = []
            while True:
                item = component_stack.pop()
                on_stack.remove(item)
                component.append(item)
                if item == node:
                    break
            result.append(tuple(sorted(component)))
    return result


def _loops(
    nodes: Sequence[ControlNode],
    edges: Sequence[ControlEdge],
    adjacency: Mapping[str, Sequence[str]],
) -> tuple[list[LoopSummary], list[ControlEdge]]:
    components = [
        component
        for component in _tarjan(adjacency)
        if len(component) > 1 or component[0] in adjacency.get(component[0], ())
    ]
    component_by_node = {node: component for component in components for node in component}
    incoming_outside: dict[tuple[str, ...], set[str]] = defaultdict(set)
    exits: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for edge in edges:
        component = component_by_node.get(edge.source)
        target_component = component_by_node.get(edge.target)
        if target_component is not None and component != target_component:
            incoming_outside[target_component].add(edge.target)
        if (
            component is not None
            and component != target_component
            and edge.role != FlowEdgeRole.CALL_ENTER
        ):
            exits[component].append(edge.id)
    back_ids: set[str] = set()
    for component in components:
        entries = tuple(sorted(incoming_outside[component]))
        if len(entries) == 1:
            back_ids.update(_natural_back_edges(component, entries[0], adjacency, edges))
    rewritten: list[ControlEdge] = []
    for edge in edges:
        source_component = component_by_node.get(edge.source)
        target_component = component_by_node.get(edge.target)
        role = edge.role
        roles = edge.semantic_roles
        if edge.id in back_ids:
            role, roles = FlowEdgeRole.LOOP_BACK, (*roles, "proven_back_edge")
        elif source_component is not None and source_component == target_component:
            role, roles = FlowEdgeRole.LOOP_BODY, (*roles, "loop_body")
        elif (
            source_component is not None
            and source_component != target_component
            and role != FlowEdgeRole.CALL_ENTER
        ):
            role, roles = FlowEdgeRole.LOOP_EXIT, (*roles, "loop_exit")
        rewritten.append(replace(edge, role=role, semantic_roles=tuple(dict.fromkeys(roles))))
    summaries = [
        LoopSummary(
            _stable_id("loop", *component),
            component,
            tuple(sorted(incoming_outside[component])),
            tuple(sorted(exits[component])),
            tuple(
                sorted(
                    edge.id
                    for edge in rewritten
                    if edge.id in back_ids and edge.source in component
                )
            ),
            len(component) == 1,
            len(incoming_outside[component]) > 1,
        )
        for component in components
    ]
    return summaries, rewritten


def _natural_back_edges(
    component: tuple[str, ...],
    entry: str,
    adjacency: Mapping[str, Sequence[str]],
    edges: Sequence[ControlEdge],
) -> set[str]:
    """Return internal edges whose target dominates their source."""

    members = set(component)
    local_adjacency = {
        node: tuple(target for target in adjacency[node] if target in members) for node in component
    }
    idom = _immediate_dominators(entry, local_adjacency)
    return {
        edge.id
        for edge in edges
        if edge.source in members
        and edge.target in members
        and _dominates(edge.target, edge.source, idom)
    }


def _immediate_dominators(entry: str, adjacency: Mapping[str, Sequence[str]]) -> dict[str, str]:
    order = _reverse_postorder(entry, adjacency)
    position = {node: index for index, node in enumerate(order)}
    predecessors: dict[str, list[str]] = defaultdict(list)
    for source, targets in adjacency.items():
        for target in targets:
            predecessors[target].append(source)
    idom = {entry: entry}
    changed = True
    while changed:
        changed = False
        for node in order[1:]:
            known = [parent for parent in predecessors[node] if parent in idom]
            if not known:
                continue
            parent = known[0]
            for candidate in known[1:]:
                parent = _intersect_idom(parent, candidate, idom, position)
            if idom.get(node) != parent:
                idom[node] = parent
                changed = True
    return idom


def _dominates(target: str, source: str, idom: Mapping[str, str]) -> bool:
    node = source
    seen: set[str] = set()
    while node not in seen:
        if node == target:
            return True
        seen.add(node)
        parent = idom.get(node)
        if parent is None or parent == node:
            return False
        node = parent
    return False


def _post_dominators(
    nodes: Sequence[ControlNode],
    adjacency: Mapping[str, Sequence[str]],
    terminals: set[str],
) -> tuple[dict[str, str | None], list[ControlDiagnostic]]:
    all_nodes = {node.id for node in nodes}
    reverse: dict[str, list[str]] = {node: [] for node in [*all_nodes, VIRTUAL_EXIT_ID]}
    for source, targets in adjacency.items():
        for target in targets:
            reverse[target].append(source)
    can_exit: set[str] = set()
    pending = list(terminals)
    while pending:
        node = pending.pop()
        if node in can_exit:
            continue
        can_exit.add(node)
        pending.extend(reverse[node])
    attachments = set(terminals) | (all_nodes - can_exit)
    forward_reversed: dict[str, list[str]] = {node: sorted(reverse[node]) for node in all_nodes}
    forward_reversed[VIRTUAL_EXIT_ID] = sorted(attachments)
    order = _reverse_postorder(VIRTUAL_EXIT_ID, forward_reversed)
    position = {node: index for index, node in enumerate(order)}
    predecessors: dict[str, list[str]] = defaultdict(list)
    for source, targets in forward_reversed.items():
        for target in targets:
            predecessors[target].append(source)
    idom: dict[str, str] = {VIRTUAL_EXIT_ID: VIRTUAL_EXIT_ID}
    changed = True
    while changed:
        changed = False
        for node in order[1:]:
            known = [item for item in predecessors[node] if item in idom]
            if not known:
                continue
            parent = known[0]
            for item in known[1:]:
                parent = _intersect_idom(parent, item, idom, position)
            if idom.get(node) != parent:
                idom[node] = parent
                changed = True
    result: dict[str, str | None] = {node: idom.get(node) for node in all_nodes}
    diagnostics: list[ControlDiagnostic] = []
    nonterminating = tuple(sorted(all_nodes - can_exit))
    if nonterminating:
        diagnostics.append(
            ControlDiagnostic(
                _stable_id("diag", "nonterminating", *nonterminating),
                "nonterminating_component",
                nonterminating,
                "Control cannot reach a concrete terminal; only the virtual exit "
                "closes the analysis.",
            )
        )
    return result, diagnostics


def _reverse_postorder(entry: str, adjacency: Mapping[str, Sequence[str]]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    stack: list[tuple[str, bool]] = [(entry, False)]
    while stack:
        node, expanded = stack.pop()
        if expanded:
            result.append(node)
            continue
        if node in seen:
            continue
        seen.add(node)
        stack.append((node, True))
        stack.extend(
            (target, False) for target in reversed(adjacency.get(node, ())) if target not in seen
        )
    result.reverse()
    return result


def _intersect_idom(
    left: str, right: str, idom: Mapping[str, str], position: Mapping[str, int]
) -> str:
    while left != right:
        while position[left] > position[right]:
            left = idom[left]
        while position[right] > position[left]:
            right = idom[right]
    return left


def _state_lineage_facts(
    gates: object,
    effects: object,
    nodes: Sequence[ControlNode],
) -> tuple[dict[str, tuple[StateRead, ...]], dict[str, tuple[StateWrite, ...]]]:
    source_nodes: dict[tuple[str, int], list[str]] = defaultdict(list)
    for node in nodes:
        if node.synthetic or node.source is None:
            continue
        path = node.source.get("path")
        start = node.source.get("start")
        if not isinstance(path, str) or not isinstance(start, Mapping):
            continue
        line = start.get("line")
        if isinstance(line, int):
            source_nodes[(path, line)].append(node.id)
    reads: dict[str, list[StateRead]] = defaultdict(list)
    if isinstance(gates, Sequence):
        for gate in gates:
            if not isinstance(gate, Requirement) or gate.status != FactStatus.PROVEN:
                continue
            key = (gate.evidence.span.path, gate.evidence.span.start_line)
            for node_id in sorted(source_nodes.get(key, ())):
                for variable in gate.variables:
                    reads[node_id].append(StateRead(variable, gate.original_expression, node_id))
    writes: dict[str, list[StateWrite]] = defaultdict(list)
    if isinstance(effects, Sequence):
        for effect in effects:
            if (
                not isinstance(effect, StateEffect)
                or effect.status != FactStatus.PROVEN
                or effect.operation != "assignment"
                or effect.variable is None
                or not _is_json_scalar(effect.value)
            ):
                continue
            key = (effect.evidence.span.path, effect.evidence.span.start_line)
            value_key = _canonical(effect.value).decode()
            for node_id in sorted(source_nodes.get(key, ())):
                writes[node_id].append(
                    StateWrite(
                        effect.variable,
                        value_key,
                        effect.original_expression,
                        node_id,
                        effect.value,
                    )
                )
    return (
        {node: tuple(sorted(values)) for node, values in reads.items()},
        {node: tuple(sorted(values)) for node, values in writes.items()},
    )


def _is_json_scalar(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _reachability_summaries(
    nodes: Sequence[ControlNode],
    adjacency: Mapping[str, Sequence[str]],
    terminals: Sequence[tuple[str, str]],
) -> dict[str, _ReachabilitySummary]:
    """Summarize downstream terminals once over the SCC condensation DAG.

    At most two representative terminal IDs are retained.  ``multiple`` records
    that more than one concrete terminal is reachable without materializing the
    complete transitive terminal set at every node.
    """

    components = _tarjan(adjacency)
    component_of = {node: index for index, component in enumerate(components) for node in component}
    successors: dict[int, set[int]] = {index: set() for index in range(len(components))}
    predecessors: dict[int, set[int]] = {index: set() for index in range(len(components))}
    for source, targets in adjacency.items():
        source_component = component_of[source]
        for target in targets:
            target_component = component_of[target]
            if source_component == target_component:
                continue
            successors[source_component].add(target_component)
            predecessors[target_component].add(source_component)
    indegree = {index: len(predecessors[index]) for index in successors}
    pending = deque(sorted(index for index, degree in indegree.items() if degree == 0))
    topological: list[int] = []
    while pending:
        component = pending.popleft()
        topological.append(component)
        for component_target in sorted(successors[component]):
            indegree[component_target] -= 1
            if indegree[component_target] == 0:
                pending.append(component_target)
    terminal_ids = {node for node, _kind in terminals}
    unresolved_nodes = {node.id for node in nodes if node.kind in {"unresolved", "scope_boundary"}}
    summaries: dict[int, _ReachabilitySummary] = {}
    for component_index in reversed(topological):
        direct = {node for node in components[component_index] if node in terminal_ids}
        samples = set(direct)
        multiple = len(direct) > 1
        unresolved = any(node in unresolved_nodes for node in components[component_index])
        for component_target in successors[component_index]:
            child = summaries[component_target]
            samples.update(child.terminal_node_ids)
            multiple = multiple or child.terminal_summary == "multiple"
            unresolved = unresolved or child.unresolved
        if len(samples) > 2:
            multiple = True
        retained = tuple(sorted(samples)[:2])
        summary_kind = (
            "multiple" if multiple or len(samples) > 1 else ("unique" if samples else "none")
        )
        summaries[component_index] = _ReachabilitySummary(retained, summary_kind, unresolved)
    return {node: summaries[component_of[node]] for node in adjacency}


def _regions(
    nodes: Sequence[ControlNode],
    edges: Sequence[ControlEdge],
    adjacency: Mapping[str, Sequence[str]],
    terminals: Sequence[tuple[str, str]],
    loops: Sequence[LoopSummary],
    ipdom: Mapping[str, str | None],
    state_reads: Mapping[str, tuple[StateRead, ...]],
    state_writes: Mapping[str, tuple[StateWrite, ...]],
    reachability: Mapping[str, _ReachabilitySummary],
) -> tuple[list[ControlArm], list[ControlRegion]]:
    node_by_id = {node.id: node for node in nodes}
    edge_by_source: dict[str, list[ControlEdge]] = defaultdict(list)
    for edge in edges:
        if edge.role != FlowEdgeRole.CALL_ENTER:
            edge_by_source[edge.source].append(edge)
    terminal_ids = {item[0] for item in terminals}
    loop_nodes = {node for loop in loops for node in loop.node_ids}
    arms: list[ControlArm] = []
    regions: list[ControlRegion] = []
    for split in sorted(node_by_id.values(), key=lambda item: item.id):
        outgoing = sorted(edge_by_source[split.id], key=lambda item: item.id)
        if split.kind == "menu" and _has_unconditional_choice(outgoing):
            outgoing = [edge for edge in outgoing if "menu_no_choice" not in edge.semantic_roles]
        if split.kind not in {"menu", "if"} or len({edge.target for edge in outgoing}) < 2:
            continue
        targets = [edge.target for edge in outgoing]
        merge = _nearest_common_postdominator(targets, ipdom)
        if merge == VIRTUAL_EXIT_ID:
            merge = None
        region_id = _stable_id(
            "region", split.id, merge or "persistent", *(edge.id for edge in outgoing)
        )
        region_arms: list[ControlArm] = []
        for ordinal, edge in enumerate(outgoing):
            members = _bounded_arm_members(
                edge.target,
                merge,
                adjacency,
                node_by_id,
                terminal_ids,
            )
            summary = reachability[edge.target]
            arm_terminals = summary.terminal_node_ids
            unresolved = edge.role == FlowEdgeRole.UNRESOLVED or summary.unresolved
            arm = ControlArm(
                _stable_id("arm", region_id, str(ordinal), edge.id),
                region_id,
                ordinal,
                edge.target,
                edge.id,
                tuple(sorted(members)),
                arm_terminals,
                unresolved,
                tuple(sorted(read for node in members for read in state_reads.get(node, ()))),
                tuple(sorted(write for node in members for write in state_writes.get(node, ()))),
                summary.terminal_summary,
            )
            region_arms.append(arm)
        classification, reasons = _classify_region(
            split, merge, region_arms, node_by_id, loop_nodes
        )
        if merge is None:
            dispatch_variables = _state_dispatch_variables(
                split.id,
                region_arms,
                adjacency,
                state_writes,
            )
            if dispatch_variables:
                reasons = (
                    *reasons,
                    "state_dispatch",
                    *(f"state_dispatch_variable:{name}" for name in dispatch_variables),
                )
        members = {split.id, *(node for arm in region_arms for node in arm.node_ids)}
        if merge is not None:
            members.add(merge)
        incoming_edges = [
            edge
            for edge in edges
            if edge.target in members
            and edge.source not in members
            and edge.role != FlowEdgeRole.CALL_ENTER
        ]
        outgoing_edges = [
            edge
            for edge in edges
            if edge.source in members
            and edge.target not in members
            and edge.role != FlowEdgeRole.CALL_ENTER
        ]
        regions.append(
            ControlRegion(
                region_id,
                split.id,
                merge,
                classification,
                tuple(arm.id for arm in region_arms),
                tuple(sorted(members)),
                None,
                all(edge.target == split.id for edge in incoming_edges),
                merge is not None and all(edge.source == merge for edge in outgoing_edges),
                reasons,
            )
        )
        arms.extend(region_arms)
    return arms, regions


def _state_dispatch_variables(
    split_node_id: str,
    arms: Sequence[ControlArm],
    adjacency: Mapping[str, Sequence[str]],
    writes_by_node: Mapping[str, tuple[StateWrite, ...]],
) -> tuple[str, ...]:
    gate_variables = {read.variable for arm in arms for read in arm.state_reads}
    if not gate_variables:
        return ()
    predecessors: dict[str, list[str]] = defaultdict(list)
    for source, targets in adjacency.items():
        for target in targets:
            predecessors[target].append(source)
    ancestors: set[str] = set()
    pending = [split_node_id]
    while pending:
        node = pending.pop()
        if node in ancestors:
            continue
        ancestors.add(node)
        pending.extend(predecessors[node])
    upstream_writes = [
        write
        for node in ancestors
        for write in writes_by_node.get(node, ())
        if node != split_node_id
    ]
    proven: list[str] = []
    for variable in sorted(gate_variables):
        arm_values: list[set[str]] = []
        valid = True
        for arm in arms:
            values = {
                value_key
                for read in arm.state_reads
                if read.variable == variable
                for value_key in [_literal_gate_value(read.expression, variable)]
                if value_key is not None
            }
            unrelated = any(read.variable != variable for read in arm.state_reads)
            if unrelated or len(values) > 1:
                valid = False
                break
            arm_values.append(values)
        literal_values = {value for values in arm_values for value in values}
        has_else = any(not values for values in arm_values)
        if not valid or not literal_values or (len(literal_values) < 2 and not has_else):
            continue
        write_values = {write.value_key for write in upstream_writes if write.variable == variable}
        if len(write_values) >= 2 and literal_values <= write_values:
            proven.append(variable)
    return tuple(proven)


def _literal_gate_value(expression: str, variable: str) -> str | None:
    try:
        node = ast.parse(expression, mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    if not isinstance(node.ops[0], ast.Eq) or not isinstance(node.left, ast.Name):
        return None
    if node.left.id != variable or not isinstance(node.comparators[0], ast.Constant):
        return None
    value = node.comparators[0].value
    return _canonical(value).decode() if _is_json_scalar(value) else None


def _has_unconditional_choice(edges: Sequence[ControlEdge]) -> bool:
    for edge in edges:
        if "menu_choice" not in edge.semantic_roles or not edge.evidence:
            continue
        metadata = edge.evidence[0].get("metadata")
        if isinstance(metadata, Mapping) and metadata.get("condition") is None:
            return True
    return False


def _nearest_common_postdominator(
    targets: Sequence[str], ipdom: Mapping[str, str | None]
) -> str | None:
    chains: list[list[str]] = []
    for target in targets:
        chain, seen = [], set()
        node: str | None = target
        while node is not None and node not in seen:
            chain.append(node)
            seen.add(node)
            node = ipdom.get(node)
        chains.append(chain)
    common = set(chains[0])
    for chain in chains[1:]:
        common.intersection_update(chain)
    return next((node for node in chains[0] if node in common), None)


def _bounded_arm_members(
    entry: str,
    merge: str | None,
    adjacency: Mapping[str, Sequence[str]],
    nodes: Mapping[str, ControlNode],
    terminals: set[str],
) -> set[str]:
    """Return direct ownership, stopping before nested region expansion."""

    pending, seen = [entry], set()
    while pending:
        node = pending.pop()
        if node == merge or node in seen:
            continue
        seen.add(node)
        if node in terminals:
            continue
        if nodes[node].kind in {"if", "menu"}:
            continue
        pending.extend(adjacency.get(node, ()))
    return seen


def _classify_region(
    split: ControlNode,
    merge: str | None,
    arms: Sequence[ControlArm],
    nodes: Mapping[str, ControlNode],
    loop_nodes: set[str],
) -> tuple[RouteClassification, tuple[str, ...]]:
    if any(arm.unresolved for arm in arms):
        return RouteClassification.UNRESOLVED, ("unresolved_target_or_behavior",)
    if split.id in loop_nodes or any(set(arm.node_ids) & loop_nodes for arm in arms):
        return RouteClassification.LOOP_CHOICE, ("choice_intersects_loop_scc",)
    if merge is not None:
        if any(arm.entry_node_id == merge or not arm.node_ids for arm in arms):
            return RouteClassification.OPTIONAL_DETOUR, (
                "concrete_common_post_dominator",
                "bypass_arm",
            )
        split_label = split.label
        crosses_procedure = nodes[merge].label != split_label or any(
            nodes[node].label != split_label for arm in arms for node in arm.node_ids
        )
        long_segment = any(len(arm.node_ids) >= 8 for arm in arms)
        if crosses_procedure or long_segment:
            return RouteClassification.RECONVERGENT_ROUTE_SEGMENT, (
                "concrete_common_post_dominator",
                "multi_scene_or_long_segment",
            )
        return RouteClassification.LOCAL_DETOUR, ("concrete_common_post_dominator",)
    terminal_sets = {(arm.terminal_summary, arm.terminal_node_ids) for arm in arms}
    if all(arm.terminal_summary != "none" for arm in arms) and (
        len(terminal_sets) > 1 or any(arm.terminal_summary == "multiple" for arm in arms)
    ):
        return RouteClassification.TERMINAL_SPLIT, ("distinct_terminals",)
    return RouteClassification.PERSISTENT_ROUTE, ("no_concrete_common_post_dominator",)


def _region_parents(
    regions: Sequence[ControlRegion], arms: Sequence[ControlArm]
) -> list[ControlRegion]:
    result: list[ControlRegion] = []
    boundary_parents: dict[str, set[str]] = defaultdict(set)
    for arm in arms:
        for node in arm.node_ids:
            boundary_parents[node].add(arm.region_id)
    region_by_id = {region.id: region for region in regions}
    for region in regions:
        parents = [
            region_by_id[parent_id]
            for parent_id in boundary_parents[region.split_node_id]
            if parent_id != region.id
        ]
        parent = min(parents, key=lambda item: (len(item.node_ids), item.id), default=None)
        result.append(replace(region, parent_region_id=parent.id if parent is not None else None))
    return result


def _ownership(
    arms: Sequence[ControlArm], regions: Sequence[ControlRegion]
) -> list[ControlOwnership]:
    region_by_id = {region.id: region for region in regions}
    candidates: dict[str, list[tuple[int, str, str | None]]] = defaultdict(list)
    for region in regions:
        for node in region.node_ids:
            candidates[node].append((len(region.node_ids), region.id, None))
    for arm in arms:
        size = len(region_by_id[arm.region_id].node_ids)
        for node in arm.node_ids:
            candidates[node].append((size, arm.region_id, arm.id))
    result: list[ControlOwnership] = []
    split_owner = {region.split_node_id: region.id for region in regions}
    for node, values in candidates.items():
        own_region = split_owner.get(node)
        if own_region is not None:
            region_id, arm_id = own_region, None
        else:
            _, region_id, arm_id = min(
                values,
                key=lambda item: (item[0], item[1], item[2] is None, item[2] or ""),
            )
        result.append(ControlOwnership(node, region_id, arm_id))
    return result
