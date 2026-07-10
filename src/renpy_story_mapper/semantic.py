"""Deterministic semantic scenes and narrative beats over the Phase 1 graph.

The semantic layer is deliberately a projection of the source-linked graph.  It
does not evaluate expressions, execute creator code, or infer dynamic targets.
Every semantic record therefore retains the graph node IDs, exact source ranges,
and typed edge evidence from which it was built.

Schema version 1 has these top-level records:

``scenes``
    One scene for each static label.  A scene contains narrative ``beats`` and
    every non-narrative ``structural_node`` owned by that label.
``boundary_nodes``
    Structural graph nodes with synthetic ownership (for example module ends).
``graph_edges``
    A stable, lossless copy of all Phase 1 typed edges.
``unresolved_transitions``
    Edges that lead to unresolved or out-of-scope behavior.

Labels are classified as ``narrative`` when they contain statically recognizable
dialogue or narration.  ``utility`` is intentionally narrow: the label must be a
static call target, contain no narrative/unknown statements or branching, and
have a return.  All other labels are ``unknown``.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import cast

SEMANTIC_SCHEMA_VERSION = 1

_NARRATOR_NAMES = frozenset({"centered", "narrator"})
_UTILITY_NODE_KINDS = frozenset(
    {
        "hide",
        "label",
        "pass",
        "pause",
        "play",
        "queue",
        "return",
        "scene",
        "show",
        "stop",
        "voice",
        "window",
        "with",
    }
)
_UNRESOLVED_EDGE_MARKERS = ("dynamic_", "missing_", "out_of_scope", "unresolved")
_STRING_START = r"(?:[rRuU]{0,2})(?:\"\"\"|'''|\"|')"
_NARRATION_RE = re.compile(rf"^{_STRING_START}")
_DIALOGUE_RE = re.compile(rf"^(?P<speaker>[A-Za-z_]\w*)(?:\s+[A-Za-z_]\w*)*\s+{_STRING_START}")


@dataclass(frozen=True)
class _Node:
    id: str
    kind: str
    label: str
    source: dict[str, object]
    source_text: str
    reachable: bool
    metadata: dict[str, object]

    @property
    def source_key(self) -> tuple[str, int, int, int, int, str]:
        start = _required_mapping(self.source.get("start"), "node source.start")
        end = _required_mapping(self.source.get("end"), "node source.end")
        return (
            _required_string(self.source.get("path"), "node source.path"),
            _required_int(start.get("line"), "node source.start.line"),
            _required_int(start.get("column"), "node source.start.column"),
            _required_int(end.get("line"), "node source.end.line"),
            _required_int(end.get("column"), "node source.end.column"),
            self.id,
        )

    def evidence(self) -> dict[str, object]:
        value: dict[str, object] = {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "source": self.source,
            "source_text": self.source_text,
            "reachable_from_entry": self.reachable,
        }
        if self.metadata:
            value["metadata"] = self.metadata
        return value


@dataclass(frozen=True)
class _Edge:
    source: str
    target: str
    kind: str
    metadata: dict[str, object]

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        return (self.source, self.target, self.kind, repr(sorted(self.metadata.items())))

    def evidence(self) -> dict[str, object]:
        value: dict[str, object] = {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
        }
        if self.metadata:
            value["metadata"] = self.metadata
        return value


@dataclass(frozen=True)
class _Narrative:
    classification: str
    character: str | None


def build_semantic_story(graph: dict[str, object]) -> dict[str, object]:
    """Build deterministic semantic schema version 1 from a Phase 1 graph.

    ``graph`` is treated as data only.  Malformed graph contracts raise
    ``ValueError`` rather than being partially interpreted.
    """

    nodes = _read_nodes(graph.get("nodes"))
    edges = _read_edges(graph.get("edges"), nodes)
    node_by_id = {node.id: node for node in nodes}
    incoming: dict[str, list[_Edge]] = defaultdict(list)
    outgoing: dict[str, list[_Edge]] = defaultdict(list)
    for edge in edges:
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)
    for values in (*incoming.values(), *outgoing.values()):
        values.sort(key=lambda edge: edge.sort_key)

    labels = [node for node in nodes if node.kind == "label"]
    labels.sort(key=lambda node: node.source_key)
    label_names: set[str] = set()
    for label_node in labels:
        name = _label_name(label_node)
        if name in label_names:
            raise ValueError(f"duplicate label node for {name!r}")
        label_names.add(name)

    scenes: list[dict[str, object]] = []
    scene_node_ids: set[str] = set()
    total_beats = 0
    total_statements = 0
    for label_node in labels:
        name = _label_name(label_node)
        owned_nodes = sorted(
            (node for node in nodes if node.label == name), key=lambda node: node.source_key
        )
        scene_node_ids.update(node.id for node in owned_nodes)
        narrative = {
            node.id: classification
            for node in owned_nodes
            if (classification := _classify_narrative(node)) is not None
        }
        grouped = _group_beats(owned_nodes, narrative, incoming, outgoing)
        beats = [_build_beat(group, narrative, incoming, outgoing, node_by_id) for group in grouped]
        total_beats += len(beats)
        total_statements += sum(len(group) for group in grouped)
        structural = [
            _structural_node(node, incoming, outgoing)
            for node in owned_nodes
            if node.id not in narrative
        ]
        label_classification, classification_evidence = _classify_label(
            owned_nodes, narrative, incoming
        )
        owned_ids = {node.id for node in owned_nodes}
        transitions = [
            edge.evidence()
            for edge in edges
            if edge.source in owned_ids or edge.target in owned_ids
        ]
        ranges = _unique_source_ranges(owned_nodes)
        scenes.append(
            {
                "id": _stable_id("scene", [label_node.id]),
                "label": name,
                "label_node_id": label_node.id,
                "classification": label_classification,
                "classification_evidence": classification_evidence,
                "reachable_from_entry": label_node.reachable,
                "source_ranges": ranges,
                "beats": beats,
                "structural_nodes": structural,
                "transitions": transitions,
            }
        )

    boundary_nodes = [
        _structural_node(node, incoming, outgoing)
        for node in sorted(nodes, key=lambda item: item.source_key)
        if node.id not in scene_node_ids
    ]
    unresolved = [
        {
            "edge": edge.evidence(),
            "source_node_id": edge.source,
            "target_node_id": edge.target,
            "target_kind": node_by_id[edge.target].kind,
        }
        for edge in edges
        if _is_unresolved_transition(edge, node_by_id)
    ]

    source_schema_version = graph.get("schema_version")
    if not isinstance(source_schema_version, int) or isinstance(source_schema_version, bool):
        raise ValueError("graph schema_version must be an integer")
    entry_label = _required_string(graph.get("entry_label"), "graph entry_label")
    scope = _required_mapping(graph.get("scope"), "graph scope")
    return {
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "source_graph_schema_version": source_schema_version,
        "entry_label": entry_label,
        "scope": dict(scope),
        "semantics": {
            "expressions_evaluated": False,
            "creator_code_executed": False,
            "dynamic_behavior_inferred": False,
            "beat_grouping": "unambiguous_fallthrough_only",
            "scene_grouping": "static_label",
            "label_classification": "deterministic_conservative",
        },
        "counts": {
            "scenes": len(scenes),
            "beats": total_beats,
            "narrative_statements": total_statements,
            "structural_nodes": len(nodes) - total_statements,
            "unresolved_transitions": len(unresolved),
        },
        "scenes": scenes,
        "boundary_nodes": boundary_nodes,
        "graph_edges": [edge.evidence() for edge in edges],
        "unresolved_transitions": unresolved,
    }


def _read_nodes(value: object) -> list[_Node]:
    raw_nodes = _required_list(value, "graph nodes")
    nodes: list[_Node] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_nodes):
        raw = _required_mapping(item, f"graph nodes[{index}]")
        node_id = _required_string(raw.get("id"), f"graph nodes[{index}].id")
        if node_id in seen:
            raise ValueError(f"duplicate graph node ID {node_id!r}")
        seen.add(node_id)
        source = dict(_required_mapping(raw.get("source"), f"graph nodes[{index}].source"))
        node = _Node(
            node_id,
            _required_string(raw.get("kind"), f"graph nodes[{index}].kind"),
            _required_string(raw.get("label"), f"graph nodes[{index}].label"),
            source,
            _required_string(raw.get("source_text"), f"graph nodes[{index}].source_text"),
            _required_bool(
                raw.get("reachable_from_entry"),
                f"graph nodes[{index}].reachable_from_entry",
            ),
            dict(_optional_mapping(raw.get("metadata"), f"graph nodes[{index}].metadata")),
        )
        # Validate the complete physical range now so malformed evidence never leaks out.
        _ = node.source_key
        nodes.append(node)
    nodes.sort(key=lambda node: node.id)
    return nodes


def _read_edges(value: object, nodes: list[_Node]) -> list[_Edge]:
    raw_edges = _required_list(value, "graph edges")
    node_ids = {node.id for node in nodes}
    edges: list[_Edge] = []
    for index, item in enumerate(raw_edges):
        raw = _required_mapping(item, f"graph edges[{index}]")
        source = _required_string(raw.get("source"), f"graph edges[{index}].source")
        target = _required_string(raw.get("target"), f"graph edges[{index}].target")
        if source not in node_ids or target not in node_ids:
            raise ValueError(f"graph edge {index} references a missing node")
        edges.append(
            _Edge(
                source,
                target,
                _required_string(raw.get("kind"), f"graph edges[{index}].kind"),
                dict(_optional_mapping(raw.get("metadata"), f"graph edges[{index}].metadata")),
            )
        )
    edges.sort(key=lambda edge: edge.sort_key)
    return edges


def _classify_narrative(node: _Node) -> _Narrative | None:
    if node.kind != "statement":
        return None
    text = node.source_text.strip()
    if _NARRATION_RE.match(text):
        return _Narrative("narration", None)
    match = _DIALOGUE_RE.match(text)
    if match is None:
        return None
    speaker = match.group("speaker")
    if speaker in _NARRATOR_NAMES:
        return _Narrative("narration", None)
    if speaker == "extend":
        return _Narrative("dialogue", None)
    return _Narrative("dialogue", speaker)


def _group_beats(
    owned_nodes: list[_Node],
    narrative: dict[str, _Narrative],
    incoming: dict[str, list[_Edge]],
    outgoing: dict[str, list[_Edge]],
) -> list[list[_Node]]:
    by_id = {node.id: node for node in owned_nodes}
    pending = {node.id for node in owned_nodes if node.id in narrative}
    groups: list[list[_Node]] = []
    while pending:
        start = min((by_id[node_id] for node_id in pending), key=lambda node: node.source_key)
        group = [start]
        pending.remove(start.id)
        current = start
        while True:
            candidates = [
                edge
                for edge in outgoing[current.id]
                if edge.kind == "fallthrough" and edge.target in pending
            ]
            if len(candidates) != 1:
                break
            edge = candidates[0]
            target = by_id[edge.target]
            if (
                target.label != current.label
                or target.reachable != current.reachable
                or len(incoming[target.id]) != 1
                or len(outgoing[current.id]) != 1
            ):
                break
            group.append(target)
            pending.remove(target.id)
            current = target
        groups.append(group)
    groups.sort(key=lambda group: group[0].source_key)
    return groups


def _build_beat(
    nodes: list[_Node],
    narrative: dict[str, _Narrative],
    incoming: dict[str, list[_Edge]],
    outgoing: dict[str, list[_Edge]],
    node_by_id: dict[str, _Node],
) -> dict[str, object]:
    ids = {node.id for node in nodes}
    statements: list[dict[str, object]] = []
    characters: set[str] = set()
    for node in nodes:
        classification = narrative[node.id]
        statement: dict[str, object] = {
            "node_id": node.id,
            "classification": classification.classification,
            "character": classification.character,
            "source": node.source,
            "source_text": node.source_text,
        }
        statements.append(statement)
        if classification.character is not None:
            characters.add(classification.character)
    incoming_edges = sorted(
        (edge for node in nodes for edge in incoming[node.id] if edge.source not in ids),
        key=lambda edge: edge.sort_key,
    )
    outgoing_edges = sorted(
        (edge for node in nodes for edge in outgoing[node.id] if edge.target not in ids),
        key=lambda edge: edge.sort_key,
    )
    conditions = _conditions_for_edges(incoming_edges, node_by_id)
    return {
        "id": _stable_id("beat", [node.id for node in nodes]),
        "label": nodes[0].label,
        "node_ids": [node.id for node in nodes],
        "reachable_from_entry": nodes[0].reachable,
        "source_ranges": [node.source for node in nodes],
        "statements": statements,
        "characters": sorted(characters),
        "conditions": conditions,
        "incoming_edges": [edge.evidence() for edge in incoming_edges],
        "outgoing_edges": [edge.evidence() for edge in outgoing_edges],
    }


def _structural_node(
    node: _Node,
    incoming: dict[str, list[_Edge]],
    outgoing: dict[str, list[_Edge]],
) -> dict[str, object]:
    value = node.evidence()
    value["incoming_edges"] = [edge.evidence() for edge in incoming[node.id]]
    value["outgoing_edges"] = [edge.evidence() for edge in outgoing[node.id]]
    return value


def _classify_label(
    nodes: list[_Node],
    narrative: dict[str, _Narrative],
    incoming: dict[str, list[_Edge]],
) -> tuple[str, list[str]]:
    if narrative:
        return "narrative", ["contains_statically_recognized_dialogue_or_narration"]
    label_nodes = [node for node in nodes if node.kind == "label"]
    static_calls = sorted(
        {
            edge.source
            for label_node in label_nodes
            for edge in incoming[label_node.id]
            if edge.kind == "call"
        }
    )
    kinds = {node.kind for node in nodes}
    if static_calls and "return" in kinds and kinds <= _UTILITY_NODE_KINDS:
        return (
            "utility",
            [
                "static_call_target",
                "contains_return",
                "contains_only_nonbranching_utility_nodes",
                "contains_no_statically_recognized_narrative",
            ],
        )
    evidence = ["insufficient_static_evidence"]
    if not static_calls:
        evidence.append("not_a_static_call_target")
    if "statement" in kinds:
        evidence.append("contains_unclassified_statement")
    if any(node.kind in {"opaque", "scope_boundary", "unresolved"} for node in nodes):
        evidence.append("contains_unknown_or_unresolved_behavior")
    return "unknown", evidence


def _conditions_for_edges(
    edges: list[_Edge], node_by_id: dict[str, _Node]
) -> list[dict[str, object]]:
    values: dict[tuple[str, str, str, str], dict[str, object]] = {}
    for edge in edges:
        condition = edge.metadata.get("condition")
        if condition is None:
            condition = node_by_id[edge.source].metadata.get("condition")
        if isinstance(condition, str):
            key = (condition, edge.source, edge.target, edge.kind)
            values[key] = {"expression": condition, "edge": edge.evidence()}
    return [values[key] for key in sorted(values)]


def _is_unresolved_transition(edge: _Edge, node_by_id: dict[str, _Node]) -> bool:
    if node_by_id[edge.target].kind in {"scope_boundary", "unresolved"}:
        return True
    return any(marker in edge.kind for marker in _UNRESOLVED_EDGE_MARKERS)


def _unique_source_ranges(nodes: list[_Node]) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    seen: set[tuple[str, int, int, int, int]] = set()
    for node in nodes:
        key = node.source_key[:-1]
        if key not in seen:
            seen.add(key)
            values.append(node.source)
    return values


def _label_name(node: _Node) -> str:
    return _required_string(node.metadata.get("name"), f"label node {node.id} metadata.name")


def _stable_id(prefix: str, node_ids: list[str]) -> str:
    identity = "\0".join(node_ids).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(identity).hexdigest()[:20]}"


def _required_mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} keys must be strings")
    return cast(dict[str, object], value)


def _optional_mapping(value: object, name: str) -> dict[str, object]:
    if value is None:
        return {}
    return _required_mapping(value, name)


def _required_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _required_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _required_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value
