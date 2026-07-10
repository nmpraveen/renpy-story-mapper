"""Deterministic semantic scenes and beats over the Phase 1 graph dictionary.

This module treats the graph as inert data.  It never evaluates an expression,
executes creator code, or guesses a dynamic target.  Semantic IDs are hashes of
stable graph IDs, and every beat retains the exact source evidence and graph
node IDs from which it was projected.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import cast

SEMANTIC_SCHEMA_VERSION = 1

_NARRATOR_NAMES = frozenset({"centered", "narrator"})
_UNRESOLVED_MARKERS = ("dynamic_", "missing_", "out_of_scope", "unresolved")
_NARRATION_RE = re.compile(
    r"^(?:[rRuU]{0,2})(?P<quote>\"\"\"|'''|\"|')(?P<text>.*)(?P=quote)(?:\s+.*)?$"
)
_DIALOGUE_RE = re.compile(
    r"^(?P<speaker>[A-Za-z_]\w*)(?:\s+[A-Za-z_]\w*)*\s+"
    r"(?:[rRuU]{0,2})(?P<quote>\"\"\"|'''|\"|')(?P<text>.*)(?P=quote)(?:\s+.*)?$"
)


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

    def provenance(self) -> dict[str, object]:
        value: dict[str, object] = {
            "graph_node_id": self.id,
            "kind": self.kind,
            "source": self.source,
            "source_text": self.source_text,
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

    def provenance(self) -> dict[str, object]:
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
    kind: str
    speaker: str | None
    text: str


def build_semantic_story(graph: dict[str, object]) -> dict[str, object]:
    """Build the stable semantic schema from a Phase 1 graph dictionary."""

    _validate_graph_header(graph)
    nodes = _read_nodes(graph.get("nodes"))
    edges = _read_edges(graph.get("edges"), nodes)
    node_by_id = {node.id: node for node in nodes}
    incoming, outgoing = _index_edges(edges)

    label_nodes = sorted((node for node in nodes if node.kind == "label"), key=_node_key)
    labels: dict[str, _Node] = {}
    for node in label_nodes:
        name = _label_name(node)
        if name in labels:
            raise ValueError(f"duplicate label node for {name!r}")
        labels[name] = node

    narrative = {
        node.id: value for node in nodes if (value := _classify_narrative(node)) is not None
    }
    scene_ids = {name: _stable_id("scene", [node.id]) for name, node in labels.items()}

    beats: list[dict[str, object]] = []
    node_to_beat: dict[str, str] = {}
    scene_to_beats: dict[str, list[str]] = defaultdict(list)
    for label in labels:
        owned = sorted((node for node in nodes if node.label == label), key=_node_key)
        scene_beats = _build_scene_beats(scene_ids[label], owned, narrative, incoming, outgoing)
        scene_beats.sort(key=_beat_key)
        for beat in scene_beats:
            beat_id = cast(str, beat["id"])
            scene_to_beats[label].append(beat_id)
            for node_id in cast(list[str], beat["graph_node_ids"]):
                node_to_beat[node_id] = beat_id
        beats.extend(scene_beats)

    scenes = [
        {
            "id": scene_ids[label],
            "label": label,
            "classification": _classify_label(
                labels[label],
                [node for node in nodes if node.label == label],
                narrative,
                incoming,
            ),
            "reachable": labels[label].reachable,
            "source": labels[label].source,
            "beat_ids": scene_to_beats[label],
        }
        for label in labels
    ]

    transitions = _build_transitions(edges, beats, node_by_id, node_to_beat, outgoing, scene_ids)
    unresolved = _build_unresolved(nodes, incoming)
    entry_label = _required_string(graph.get("entry_label"), "graph entry_label")
    if entry_label not in scene_ids:
        raise ValueError(f"entry label {entry_label!r} has no scene")
    return {
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "entry_scene_id": scene_ids[entry_label],
        "scenes": scenes,
        "beats": beats,
        "transitions": transitions,
        "unresolved": unresolved,
    }


def _build_scene_beats(
    scene_id: str,
    nodes: list[_Node],
    narrative: dict[str, _Narrative],
    incoming: dict[str, list[_Edge]],
    outgoing: dict[str, list[_Edge]],
) -> list[dict[str, object]]:
    by_id = {node.id: node for node in nodes}
    claimed: set[str] = {node.id for node in nodes if node.kind == "label"}
    result: list[dict[str, object]] = []

    for group in _group_narrative(nodes, narrative, incoming, outgoing):
        claimed.update(node.id for node in group)
        result.append(_narrative_beat(scene_id, group, narrative))

    for node in nodes:
        if node.id in claimed or node.kind != "menu":
            continue
        bundle = [node]
        bundle.extend(
            by_id[edge.target]
            for edge in outgoing[node.id]
            if edge.kind == "menu_choice" and edge.target in by_id
        )
        bundle.extend(
            candidate
            for candidate in nodes
            if candidate.kind == "merge"
            and candidate.metadata.get("control") == "menu"
            and _same_source(candidate, node)
        )
        bundle = _unique_nodes(bundle)
        claimed.update(item.id for item in bundle)
        result.append(_structural_beat(scene_id, "choice", bundle))

    for node in nodes:
        if node.id in claimed or node.kind != "if":
            continue
        bundle = [node]
        bundle.extend(
            by_id[edge.target]
            for edge in outgoing[node.id]
            if edge.kind == "condition" and edge.target in by_id
        )
        bundle.extend(
            candidate
            for candidate in nodes
            if candidate.kind == "merge"
            and candidate.metadata.get("control") == "if"
            and _same_source(candidate, node)
        )
        bundle = _unique_nodes(bundle)
        claimed.update(item.id for item in bundle)
        result.append(_structural_beat(scene_id, "condition", bundle))

    for node in nodes:
        if node.id in claimed or node.kind in {"scope_boundary", "unresolved"}:
            continue
        kind = node.kind
        if kind in {"module_end"}:
            kind = "ending"
        elif kind == "return":
            kind = (
                "return" if any(edge.kind == "return" for edge in outgoing[node.id]) else "ending"
            )
        claimed.add(node.id)
        result.append(_structural_beat(scene_id, kind, [node]))
    return result


def _narrative_beat(
    scene_id: str, nodes: list[_Node], narrative: dict[str, _Narrative]
) -> dict[str, object]:
    content = [
        {
            "kind": narrative[node.id].kind,
            "speaker": narrative[node.id].speaker,
            "text": narrative[node.id].text,
            "source": node.source,
        }
        for node in nodes
    ]
    return {
        "id": _stable_id("beat", [node.id for node in nodes]),
        "scene_id": scene_id,
        "kind": "narrative",
        "reachable": all(node.reachable for node in nodes),
        "source": _combined_source(nodes),
        "graph_node_ids": [node.id for node in nodes],
        "content": content,
        "provenance": [node.provenance() for node in nodes],
    }


def _structural_beat(scene_id: str, kind: str, nodes: list[_Node]) -> dict[str, object]:
    ordered = sorted(nodes, key=_node_key)
    value: dict[str, object] = {
        "id": _stable_id(f"beat_{kind}", [node.id for node in ordered]),
        "scene_id": scene_id,
        "kind": kind,
        "reachable": all(node.reachable for node in ordered),
        "source": _combined_source(ordered),
        "graph_node_ids": [node.id for node in ordered],
        "provenance": [node.provenance() for node in ordered],
    }
    if kind == "choice":
        value["choices"] = [
            {
                "caption": node.metadata.get("caption"),
                "condition": node.metadata.get("condition"),
                "source": node.source,
            }
            for node in ordered
            if node.kind == "menu_choice"
        ]
    elif kind == "condition":
        value["branches"] = [
            {"condition": node.metadata.get("condition"), "source": node.source}
            for node in ordered
            if node.kind == "if_branch"
        ]
    elif len(ordered) == 1:
        value["source_text"] = ordered[0].source_text
        if ordered[0].metadata:
            value["metadata"] = ordered[0].metadata
    return value


def _build_transitions(
    edges: list[_Edge],
    beats: list[dict[str, object]],
    node_by_id: dict[str, _Node],
    node_to_beat: dict[str, str],
    outgoing: dict[str, list[_Edge]],
    scene_ids: dict[str, str],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    skipped = {"branch_body", "call_continuation", "choice_body", "label_entry"}
    for edge in edges:
        if edge.kind in skipped:
            continue
        source_node = node_by_id[edge.source]
        source_beat = node_to_beat.get(edge.source)
        normalized_kind = _transition_kind(edge.kind)
        if normalized_kind is None:
            continue
        target_node_id, target_beat = _semantic_target(
            edge.target,
            source_beat,
            node_to_beat,
            outgoing,
            traverse_source_beat=edge.kind
            in {"condition", "condition_false", "menu_choice", "menu_no_choice"},
        )
        resolved = not _edge_is_unresolved(edge, node_by_id)
        if (
            source_beat is not None
            and source_beat == target_beat
            and normalized_kind == "fallthrough"
        ):
            continue
        target_node = node_by_id[target_node_id]
        evidence_node = (
            node_by_id[edge.target] if normalized_kind in {"choice", "condition"} else source_node
        )
        value: dict[str, object] = {
            "id": _stable_id(
                f"transition_{normalized_kind}",
                [edge.source, edge.target, target_node_id],
            ),
            "kind": normalized_kind,
            "resolved": resolved,
            "source_label": source_node.label,
            "target_label": target_node.label if resolved else None,
            "source_scene_id": scene_ids.get(source_node.label),
            "target_scene_id": scene_ids.get(target_node.label) if resolved else None,
            "source_beat_id": source_beat,
            "target_beat_id": target_beat if resolved else None,
            "source": evidence_node.source,
            "graph_edge": edge.provenance(),
        }
        if normalized_kind == "choice":
            choice = node_by_id[edge.target]
            value["caption"] = choice.metadata.get("caption")
            value["condition"] = choice.metadata.get("condition")
        elif normalized_kind == "condition":
            value["condition"] = edge.metadata.get("condition")
        result.append(value)

    for beat in beats:
        if beat["kind"] != "ending":
            continue
        beat_id = cast(str, beat["id"])
        graph_ids = cast(list[str], beat["graph_node_ids"])
        node = node_by_id[graph_ids[0]]
        result.append(
            {
                "id": _stable_id("transition_ending", [beat_id]),
                "kind": "ending",
                "resolved": True,
                "source_label": node.label,
                "target_label": None,
                "source_scene_id": scene_ids.get(node.label),
                "target_scene_id": None,
                "source_beat_id": beat_id,
                "target_beat_id": None,
                "source": cast(dict[str, object], beat["source"]),
                "graph_edge": None,
            }
        )
    result.sort(key=_transition_key)
    return result


def _build_unresolved(
    nodes: list[_Node], incoming: dict[str, list[_Edge]]
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for node in sorted(nodes, key=_node_key):
        if node.kind not in {"scope_boundary", "unresolved"}:
            continue
        incoming_ids = sorted({edge.source for edge in incoming[node.id]})
        reason = node.metadata.get("reason")
        if not isinstance(reason, str):
            reason = "out_of_scope" if node.kind == "scope_boundary" else "unresolved"
        result.append(
            {
                "id": _stable_id("unresolved", [*incoming_ids, node.id]),
                "kind": reason,
                "expression": node.metadata.get("expression"),
                "resolved": False,
                "source": node.source,
                "source_label": node.label,
                "source_text": node.source_text,
                "graph_node_ids": [*incoming_ids, node.id],
                "metadata": node.metadata,
            }
        )
    return result


def _group_narrative(
    nodes: list[_Node],
    narrative: dict[str, _Narrative],
    incoming: dict[str, list[_Edge]],
    outgoing: dict[str, list[_Edge]],
) -> list[list[_Node]]:
    by_id = {node.id: node for node in nodes}
    pending = {node.id for node in nodes if node.id in narrative}
    groups: list[list[_Node]] = []
    while pending:
        current = min((by_id[node_id] for node_id in pending), key=_node_key)
        group = [current]
        pending.remove(current.id)
        while True:
            candidates = [
                edge
                for edge in outgoing[current.id]
                if edge.kind == "fallthrough" and edge.target in pending
            ]
            if len(candidates) != 1:
                break
            target = by_id[candidates[0].target]
            if (
                target.label != current.label
                or target.reachable != current.reachable
                or target.source_key[0] != current.source_key[0]
                or len(incoming[target.id]) != 1
                or len(outgoing[current.id]) != 1
            ):
                break
            group.append(target)
            pending.remove(target.id)
            current = target
        groups.append(group)
    groups.sort(key=lambda group: _node_key(group[0]))
    return groups


def _classify_narrative(node: _Node) -> _Narrative | None:
    if node.kind != "statement":
        return None
    text = node.source_text.strip()
    narration = _NARRATION_RE.match(text)
    if narration is not None:
        return _Narrative("narration", None, narration.group("text"))
    dialogue = _DIALOGUE_RE.match(text)
    if dialogue is None:
        return None
    speaker = dialogue.group("speaker")
    if speaker in _NARRATOR_NAMES:
        return _Narrative("narration", None, dialogue.group("text"))
    if speaker == "extend":
        return _Narrative("dialogue", None, dialogue.group("text"))
    return _Narrative("dialogue", speaker, dialogue.group("text"))


def _classify_label(
    label_node: _Node,
    nodes: list[_Node],
    narrative: dict[str, _Narrative],
    incoming: dict[str, list[_Edge]],
) -> str:
    if any(node.id in narrative for node in nodes):
        return "narrative"
    static_call_target = any(edge.kind == "call" for edge in incoming[label_node.id])
    has_return = any(node.kind == "return" for node in nodes)
    allowed = all(
        node.kind in {"label", "return"}
        or (
            node.kind == "opaque"
            and node.metadata.get("reason") == "embedded_python_not_executed"
            and node.metadata.get("executed") is False
        )
        for node in nodes
    )
    if static_call_target and has_return and allowed:
        return "utility"
    return "unknown"


def _semantic_target(
    start: str,
    source_beat: str | None,
    node_to_beat: dict[str, str],
    outgoing: dict[str, list[_Edge]],
    *,
    traverse_source_beat: bool,
) -> tuple[str, str | None]:
    pending = deque([start])
    seen: set[str] = set()
    traversable = {
        "branch_body",
        "choice_body",
        "condition_false",
        "fallthrough",
        "label_entry",
        "menu_no_choice",
    }
    while pending:
        node_id = pending.popleft()
        if node_id in seen:
            continue
        seen.add(node_id)
        beat_id = node_to_beat.get(node_id)
        if beat_id is not None and beat_id != source_beat:
            return node_id, beat_id
        if beat_id is not None and not traverse_source_beat:
            return node_id, beat_id
        for edge in outgoing[node_id]:
            if edge.kind in traversable:
                pending.append(edge.target)
    return start, node_to_beat.get(start)


def _transition_kind(kind: str) -> str | None:
    if kind == "menu_choice":
        return "choice"
    if kind in {"condition", "condition_false"}:
        return "condition"
    if kind == "menu_no_choice":
        return "fallthrough"
    if "jump" in kind:
        return "jump"
    if "call" in kind:
        return "call"
    if kind in {"fallthrough", "return"}:
        return kind
    if "unresolved" in kind:
        return "unresolved"
    return None


def _edge_is_unresolved(edge: _Edge, node_by_id: dict[str, _Node]) -> bool:
    if node_by_id[edge.target].kind in {"scope_boundary", "unresolved"}:
        return True
    return any(marker in edge.kind for marker in _UNRESOLVED_MARKERS)


def _combined_source(nodes: list[_Node]) -> dict[str, object]:
    ordered = sorted(nodes, key=_node_key)
    paths = {_required_string(node.source.get("path"), "node source.path") for node in ordered}
    if len(paths) != 1:
        raise ValueError("a semantic beat cannot span multiple source paths")
    starts = [_required_mapping(node.source.get("start"), "node source.start") for node in ordered]
    ends = [_required_mapping(node.source.get("end"), "node source.end") for node in ordered]
    start = min(starts, key=_position_key)
    end = max(ends, key=_position_key)
    return {"path": paths.pop(), "start": dict(start), "end": dict(end)}


def _index_edges(
    edges: list[_Edge],
) -> tuple[dict[str, list[_Edge]], dict[str, list[_Edge]]]:
    incoming: dict[str, list[_Edge]] = defaultdict(list)
    outgoing: dict[str, list[_Edge]] = defaultdict(list)
    for edge in edges:
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)
    for values in (*incoming.values(), *outgoing.values()):
        values.sort(key=lambda edge: edge.sort_key)
    return incoming, outgoing


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
        node = _Node(
            node_id,
            _required_string(raw.get("kind"), f"graph nodes[{index}].kind"),
            _required_string(raw.get("label"), f"graph nodes[{index}].label"),
            dict(_required_mapping(raw.get("source"), f"graph nodes[{index}].source")),
            _required_string(raw.get("source_text"), f"graph nodes[{index}].source_text"),
            _required_bool(
                raw.get("reachable_from_entry"),
                f"graph nodes[{index}].reachable_from_entry",
            ),
            dict(_optional_mapping(raw.get("metadata"), f"graph nodes[{index}].metadata")),
        )
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


def _validate_graph_header(graph: dict[str, object]) -> None:
    schema_version = graph.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ValueError("graph schema_version must be an integer")
    _required_string(graph.get("entry_label"), "graph entry_label")


def _unique_nodes(nodes: list[_Node]) -> list[_Node]:
    return sorted({node.id: node for node in nodes}.values(), key=_node_key)


def _same_source(left: _Node, right: _Node) -> bool:
    return left.source == right.source


def _label_name(node: _Node) -> str:
    return _required_string(node.metadata.get("name"), f"label node {node.id} metadata.name")


def _stable_id(prefix: str, values: list[str]) -> str:
    identity = "\0".join(values).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(identity).hexdigest()[:20]}"


def _node_key(node: _Node) -> tuple[str, int, int, int, int, str]:
    return node.source_key


def _beat_key(beat: dict[str, object]) -> tuple[str, int, int, str]:
    source = _required_mapping(beat.get("source"), "beat source")
    start = _required_mapping(source.get("start"), "beat source.start")
    return (
        _required_string(source.get("path"), "beat source.path"),
        _required_int(start.get("line"), "beat source.start.line"),
        _required_int(start.get("column"), "beat source.start.column"),
        _required_string(beat.get("id"), "beat id"),
    )


def _transition_key(transition: dict[str, object]) -> tuple[str, int, int, str]:
    source = _required_mapping(transition.get("source"), "transition source")
    start = _required_mapping(source.get("start"), "transition source.start")
    return (
        _required_string(source.get("path"), "transition source.path"),
        _required_int(start.get("line"), "transition source.start.line"),
        _required_int(start.get("column"), "transition source.start.column"),
        _required_string(transition.get("id"), "transition id"),
    )


def _position_key(position: dict[str, object]) -> tuple[int, int]:
    return (
        _required_int(position.get("line"), "source position.line"),
        _required_int(position.get("column"), "source position.column"),
    )


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
