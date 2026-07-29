"""Small progressive story projection over persisted parsed Ren'Py facts.

This is intentionally not another parser or solver.  It reads the existing
``parsed_source`` payloads, follows their labels and static control statements, and stops at
caller-selected story boundaries.  Unsupported transfers stay explicit.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol, cast

from renpy_story_mapper.project import PayloadRecord, Project

PHASE05_PROGRESSIVE_KEY = "phase05_progressive"
PHASE05_PROGRESSIVE_WALK_KEY = "phase05_progressive_walk"
PHASE05_PROGRESSIVE_MARKER = "Phase 05 progressive story walk"

_ASSIGNMENT = re.compile(
    r"^\$\s*(?P<variable>[A-Za-z_]\w*)\s*(?P<operator>\+=|-=|=)\s*(?P<expression>.+?)\s*$"
)
_IDENTIFIER = re.compile(r"\b[A-Za-z_]\w*\b")
_QUOTED_STORY = re.compile(r"^(?:(?P<speaker>[A-Za-z_]\w*)\s+)?(?P<text>['\"].*)$")
_IGNORED_IDENTIFIERS = frozenset(
    {"True", "False", "None", "and", "or", "not", "in", "is", "persistent"}
)
_TECHNICAL_SIMPLE_KINDS = frozenset(
    {
        "scene",
        "show",
        "hide",
        "play",
        "stop",
        "queue",
        "voice",
        "with",
        "pause",
        "pass",
        "window",
    }
)


class ParsedPayloadProject(Protocol):
    def payload_keys(self, collection: str) -> tuple[str, ...]: ...

    def payload(self, collection: str, key: str) -> object | None: ...


def build_progressive_story_page(
    project: ParsedPayloadProject,
    *,
    entry_label: str,
    stop_labels: Iterable[str],
    terminal_labels: Mapping[str, str] | None = None,
    source_paths: Iterable[str] | None = None,
    label_titles: Mapping[str, str] | None = None,
    backlink_variables: Iterable[str] = (),
    state_variables: Iterable[str] = (),
    page_title: str | None = None,
    page_overview: str | None = None,
    choice_titles: Mapping[str, str] | None = None,
    arm_summaries: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Build a reader-compatible page from one deterministic progressive walk."""

    parsed = _parsed_payloads(project)
    walk = build_progressive_story_from_parsed(
        parsed,
        entry_label=entry_label,
        stop_labels=stop_labels,
        terminal_labels=terminal_labels,
        source_paths=source_paths,
        label_titles=label_titles,
        backlink_variables=backlink_variables,
        state_variables=state_variables,
    )
    return _project_reader_page(
        walk,
        title=page_title,
        overview=page_overview,
        choice_titles=choice_titles,
        arm_summaries=arm_summaries,
    )


def persist_progressive_story_page(
    project: Project,
    *,
    entry_label: str,
    stop_labels: Iterable[str],
    terminal_labels: Mapping[str, str] | None = None,
    source_paths: Iterable[str] | None = None,
    label_titles: Mapping[str, str] | None = None,
    backlink_variables: Iterable[str] = (),
    state_variables: Iterable[str] = (),
    page_title: str | None = None,
    page_overview: str | None = None,
    choice_titles: Mapping[str, str] | None = None,
    arm_summaries: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Persist the strict reader page and its separate factual walk."""

    parsed = _parsed_payloads(project)
    walk = build_progressive_story_from_parsed(
        parsed,
        entry_label=entry_label,
        stop_labels=stop_labels,
        terminal_labels=terminal_labels,
        source_paths=source_paths,
        label_titles=label_titles,
        backlink_variables=backlink_variables,
        state_variables=state_variables,
    )
    page = _project_reader_page(
        walk,
        title=page_title,
        overview=page_overview,
        choice_titles=choice_titles,
        arm_summaries=arm_summaries,
    )
    dependencies = project.payload_keys("parsed_source")
    project.write_payloads(
        [
            PayloadRecord(
                "story_map_v2",
                PHASE05_PROGRESSIVE_WALK_KEY,
                walk,
                dependencies,
            ),
            PayloadRecord(
                "story_map_v2",
                PHASE05_PROGRESSIVE_KEY,
                page,
                dependencies,
            )
        ]
    )
    return page


def _project_reader_page(
    walk: Mapping[str, object],
    *,
    title: str | None,
    overview: str | None,
    choice_titles: Mapping[str, str] | None,
    arm_summaries: Mapping[str, str] | None,
) -> dict[str, object]:
    """Project the graph into the existing strict Story Map page contract."""

    nodes = {
        _text(node.get("id"), "walk node id"): node
        for raw in _list(walk.get("nodes"), "walk nodes")
        for node in (_mapping(raw, "walk node"),)
    }
    edges = [_mapping(raw, "walk edge") for raw in _list(walk.get("edges"), "walk edges")]
    outgoing: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for edge in edges:
        outgoing[_text(edge.get("source"), "walk edge source")].append(edge)
    for values in outgoing.values():
        values.sort(key=lambda edge: (_integer(edge.get("order", 0), "walk edge order"), str(edge)))

    control_ids = {
        node_id for node_id, node in nodes.items() if node.get("type") in {"choice", "condition"}
    }
    incoming_arms: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for control_id in control_ids:
        control = nodes[control_id]
        for edge in outgoing.get(control_id, ()):
            if not _is_control_edge(control, edge):
                continue
            arm_id = _arm_id(control_id, edge)
            found = _first_downstream_controls(
                _text(edge.get("target"), "choice target"), nodes, outgoing
            )
            for found_id in found:
                incoming_arms[found_id].add((control_id, arm_id))
    nested_parent = {
        control_id: next(iter(parents))
        for control_id, parents in incoming_arms.items()
        if len(parents) == 1
    }
    changed = True
    while changed:
        changed = False
        for control_id, parents in incoming_arms.items():
            if control_id in nested_parent:
                continue
            parent_controls = {parent for parent, _arm in parents}
            if len(parent_controls) != 1:
                continue
            parent = next(iter(parent_controls))
            inherited = nested_parent.get(parent)
            if inherited is not None:
                nested_parent[control_id] = inherited
                changed = True
    nested_children: dict[tuple[str, str], list[str]] = defaultdict(list)
    for control_id, owner in nested_parent.items():
        nested_children[owner].append(control_id)
    root_control_ids = control_ids.difference(nested_parent)

    def project_choice(control_id: str, ancestors: frozenset[str]) -> dict[str, object]:
        if control_id in ancestors:
            raise ValueError(f"choice cycle at {control_id!r}")
        node = nodes[control_id]
        source = _reader_source(_mapping(node.get("source"), "choice source"))
        choice_edges = [
            edge for edge in outgoing.get(control_id, ()) if _is_control_edge(node, edge)
        ]
        first_caption = _edge_caption(choice_edges[0])
        default_title = (
            f"story:Route gate: {_text(node.get('condition'), 'route condition')}"
            if node.get("type") == "condition"
            else f"story:{first_caption}"
        )
        title_keys = (node.get("condition"), first_caption)
        choice_title = next(
            (
                choice_titles[key]
                for key in title_keys
                if isinstance(key, str) and choice_titles is not None and key in choice_titles
            ),
            default_title,
        )
        arms: list[dict[str, object]] = []
        for edge in choice_edges:
            arm_id = _arm_id(control_id, edge)
            target = _text(edge.get("target"), "choice target")
            trace = _trace_arm(target, nodes, outgoing, control_ids)
            caption = _edge_caption(edge)
            evidence = _mapping(edge.get("evidence", node.get("source")), "choice evidence")
            summary_key = (
                f"{_text(evidence.get('path'), 'choice path')}:"
                f"{_integer(evidence.get('start_line'), 'choice line')}|{caption}"
            )
            arm_summary = (
                (arm_summaries or {}).get(summary_key)
                or (arm_summaries or {}).get(caption)
                or str(trace["outline_summary"])
                or caption
            )
            nested = sorted(
                nested_children.get((control_id, arm_id), ()),
                key=lambda candidate: _node_sort_key(nodes[candidate]),
            )
            target_node = nodes[target]
            destination_kind = (
                "terminal" if target_node.get("type") == "terminal" else "generic_scene"
            )
            arms.append(
                {
                    "selection_id": arm_id,
                    "caption": caption,
                    "outcome_summary": arm_summary,
                    "outline_summary": str(trace["outline_summary"]) or caption,
                    "detail_summary": str(trace["detail_summary"]) or caption,
                    "condition": (
                        edge.get("condition")
                        if isinstance(edge.get("condition"), str)
                        else None
                    ),
                    "effects": trace["effects"],
                    "destination_id": target,
                    "rejoin_node_id": trace["boundary_id"],
                    "rejoin_line": trace["boundary_line"],
                    "reachability": "reachable",
                    "warnings": [],
                    "binding": _reader_binding(
                        arm_id,
                        destination_kind,
                        target,
                        "story_map_v2_arm",
                        _reader_source(
                            evidence
                        ),
                    ),
                    "rejoin_binding": None,
                    "nested_choices": [
                        project_choice(candidate, ancestors | {control_id}) for candidate in nested
                    ],
                }
            )
        return {"key": choice_title, "source": source, "arms": arms}

    entry_label = _text(walk.get("entry_label"), "walk entry label")
    entry_node = next(
        (
            node
            for node in nodes.values()
            if node.get("label") == entry_label and node.get("type") == "label"
        ),
        None,
    )
    if entry_node is None:
        raise ValueError("progressive walk has no entry node")
    page_title = title or f"Progressive story from {_humanize(entry_label)}"
    page_overview = overview or (
        f"The story is followed from {entry_label} until "
        f"{', '.join(cast(list[str], walk.get('stop_labels', [])))}."
    )
    warnings: list[str] = []
    backlinks = _list(walk.get("state_backlinks"), "walk state backlinks")
    backlink_variables = sorted(
        {
            _text(_mapping(item, "state backlink").get("variable"), "backlink variable")
            for item in backlinks
        }
    )
    if backlink_variables:
        warnings.append(f"Earlier state controls this route: {', '.join(backlink_variables)}.")
    root_choices = [
        project_choice(control_id, frozenset())
        for control_id in sorted(root_control_ids, key=lambda item: _node_sort_key(nodes[item]))
    ]
    event_id = f"walk:event:{entry_label}"
    event_source = _reader_source(_mapping(entry_node.get("source"), "entry source"))
    event_trace = _trace_arm(
        _text(entry_node.get("id"), "entry node id"), nodes, outgoing, control_ids
    )
    return {
        "schema": "story-map-v2-page-v1",
        "status": "synthesized",
        "reason": None,
        "title": page_title,
        "overview": page_overview,
        "analysis_notes": [
            f"{PHASE05_PROGRESSIVE_MARKER} projected from parser-owned control flow."
        ],
        "sections": [
            {
                "id": "phase05-progressive-proof",
                "title": page_title,
                "summary": page_overview,
                "events": [
                    {
                        "selection_id": event_id,
                        "title": page_title,
                        "summary": page_overview,
                        "outline_summary": (
                            str(event_trace["outline_summary"]) or page_overview
                        ),
                        "detail_summary": (
                            str(event_trace["detail_summary"]) or page_overview
                        ),
                        "characters": [],
                        "reachability": "reachable",
                        "warnings": warnings,
                        "binding": _reader_binding(
                            event_id,
                            "generic_scene",
                            _text(entry_node.get("id"), "entry node id"),
                            "story_map_v2_event",
                            event_source,
                        ),
                        "choices": root_choices,
                    }
                ],
            }
        ],
    }


def _arm_id(choice_id: str, edge: Mapping[str, object]) -> str:
    suffix = edge.get("order", edge.get("kind"))
    if not isinstance(suffix, int | str):
        raise ValueError("choice arm has no stable order")
    return f"{choice_id}:arm:{suffix}"


def _is_control_edge(
    node: Mapping[str, object], edge: Mapping[str, object]
) -> bool:
    if node.get("type") == "choice":
        return edge.get("kind") == "choice"
    return str(edge.get("kind", "")).startswith("condition")


def _edge_caption(edge: Mapping[str, object]) -> str:
    caption = edge.get("caption")
    if isinstance(caption, str) and caption:
        return caption
    condition = edge.get("condition")
    return condition if isinstance(condition, str) and condition else "Otherwise"


def _first_downstream_controls(
    start: str,
    nodes: Mapping[str, Mapping[str, object]],
    outgoing: Mapping[str, Sequence[Mapping[str, object]]],
) -> set[str]:
    pending = deque([start])
    seen: set[str] = set()
    found: set[str] = set()
    while pending:
        node_id = pending.popleft()
        if node_id in seen or node_id not in nodes:
            continue
        seen.add(node_id)
        kind = nodes[node_id].get("type")
        if kind in {"choice", "condition"}:
            found.add(node_id)
            continue
        if kind in {"rejoin", "terminal", "unresolved"}:
            continue
        pending.extend(
            _text(edge.get("target"), "walk edge target")
            for edge in outgoing.get(node_id, ())
        )
    return found


def _trace_arm(
    start: str,
    nodes: Mapping[str, Mapping[str, object]],
    outgoing: Mapping[str, Sequence[Mapping[str, object]]],
    choice_ids: set[str],
) -> dict[str, object]:
    pending = deque([start])
    seen: set[str] = set()
    story_material: list[str] = []
    corridor_material: list[str] = []
    effects: list[str] = []
    boundaries: list[tuple[str, int]] = []
    while pending:
        node_id = pending.popleft()
        if node_id in seen or node_id not in nodes or node_id in choice_ids:
            continue
        seen.add(node_id)
        node = nodes[node_id]
        kind = node.get("type")
        if kind == "corridor" and isinstance(node.get("text"), str):
            text = str(node["text"]).strip()
            if text:
                story_material.append(text)
                corridor_material.append(text)
        elif kind == "effect":
            effects.append(_text(node.get("title"), "effect title"))
        elif kind in {"destination", "label"}:
            story_material.append(_text(node.get("title"), f"{kind} title"))
        elif kind in {"rejoin", "terminal", "unresolved"}:
            source = _mapping(node.get("source"), "boundary source")
            boundaries.append((node_id, _integer(source.get("start_line"), "boundary line")))
            story_material.append(_text(node.get("title"), "boundary title"))
            continue
        pending.extend(
            _text(edge.get("target"), "walk edge target")
            for edge in outgoing.get(node_id, ())
        )
    boundary_id, boundary_line = (
        min(boundaries, key=lambda item: item[1]) if boundaries else (None, None)
    )
    material: list[str] = []
    for item in story_material:
        if not material or material[-1] != item:
            material.append(item)
    concrete = list(dict.fromkeys(corridor_material))
    outline_source = concrete[0] if concrete else (material[0] if material else "")
    outline_summary = next(
        (line.strip() for line in outline_source.splitlines() if line.strip()), ""
    )
    return {
        "outline_summary": outline_summary,
        "detail_summary": "\n".join(material),
        "effects": list(dict.fromkeys(effects)),
        "boundary_id": boundary_id,
        "boundary_line": boundary_line,
    }


def _reader_source(source: Mapping[str, object]) -> dict[str, object]:
    return {
        "relative_path": _text(source.get("path"), "source path"),
        "start_line": _integer(source.get("start_line"), "source start line"),
        "end_line": _integer(source.get("end_line"), "source end line"),
    }


def _reader_binding(
    selection_id: str,
    destination_kind: str,
    target_id: str,
    detail_kind: str,
    source: Mapping[str, object],
) -> dict[str, object]:
    return {
        "selection_id": selection_id,
        "destination_kind": destination_kind,
        "target_id": target_id,
        "detail_kind": detail_kind,
        "detail_id": selection_id,
        "source": dict(source),
    }


def build_progressive_story_from_parsed(
    parsed_sources: Sequence[Mapping[str, object]],
    *,
    entry_label: str,
    stop_labels: Iterable[str],
    terminal_labels: Mapping[str, str] | None = None,
    source_paths: Iterable[str] | None = None,
    label_titles: Mapping[str, str] | None = None,
    backlink_variables: Iterable[str] = (),
    state_variables: Iterable[str] = (),
) -> dict[str, object]:
    """Project already parsed source payloads; useful for focused tests and tooling."""

    builder = _ProgressiveBuilder(
        parsed_sources,
        entry_label=entry_label,
        stop_labels=frozenset(stop_labels),
        terminal_labels={} if terminal_labels is None else dict(terminal_labels),
        source_paths=None if source_paths is None else frozenset(source_paths),
        label_titles={} if label_titles is None else dict(label_titles),
        backlink_variables=frozenset(backlink_variables),
        state_variables=frozenset(state_variables),
    )
    return builder.build()


def _parsed_payloads(project: ParsedPayloadProject) -> tuple[Mapping[str, object], ...]:
    values: list[Mapping[str, object]] = []
    for key in project.payload_keys("parsed_source"):
        value = project.payload("parsed_source", key)
        if not isinstance(value, dict):
            raise ValueError(f"parsed_source/{key} must be an object")
        values.append(cast(Mapping[str, object], value))
    return tuple(values)


class _ProgressiveBuilder:
    def __init__(
        self,
        parsed_sources: Sequence[Mapping[str, object]],
        *,
        entry_label: str,
        stop_labels: frozenset[str],
        terminal_labels: dict[str, str],
        source_paths: frozenset[str] | None,
        label_titles: dict[str, str],
        backlink_variables: frozenset[str],
        state_variables: frozenset[str],
    ) -> None:
        self.parsed_sources = parsed_sources
        self.entry_label = entry_label
        self.stop_labels = stop_labels
        self.terminal_labels = terminal_labels
        self.source_paths = source_paths
        self.label_titles = label_titles
        self.backlink_variables = backlink_variables
        self.state_variables = state_variables
        self.labels: dict[str, Mapping[str, object]] = {}
        self.label_paths: dict[str, str] = {}
        self.fallthrough: dict[str, str | None] = {}
        self.nodes: dict[str, dict[str, object]] = {}
        self.edges: list[dict[str, object]] = []
        self._node_ordinals: dict[tuple[str, str, int], int] = defaultdict(int)
        self._label_nodes: dict[str, str] = {}
        self._index_labels()

    def build(self) -> dict[str, object]:
        if self.entry_label not in self.labels:
            raise ValueError(f"entry label {self.entry_label!r} was not found in selected sources")

        label_nodes = {name: self._label_node(name) for name in self.labels}
        for name, label in self.labels.items():
            if name in self.stop_labels or name in self.terminal_labels:
                continue
            continuation_name = self.fallthrough.get(name)
            continuation = (
                label_nodes[continuation_name]
                if continuation_name is not None
                else self._boundary_node(name, "Source module ends")
            )
            entry = self._build_sequence(_list(label.get("body"), "label body"), continuation)
            self._edge(label_nodes[name], entry, "label_entry")

        reachable = self._reachable(label_nodes[self.entry_label])
        nodes = [self.nodes[node_id] for node_id in reachable]
        nodes.sort(key=_node_sort_key)
        edges = [
            edge
            for edge in self.edges
            if edge["source"] in reachable and edge["target"] in reachable
        ]
        edges.sort(key=lambda item: (str(item["source"]), str(item["target"]), str(item["kind"])))

        backlinks = self._state_backlinks(reachable)
        backlinks_by_variable: dict[str, list[str]] = defaultdict(list)
        for item in backlinks:
            backlinks_by_variable[str(item["variable"])].append(str(item["id"]))
        for node in nodes:
            condition = node.get("condition")
            if isinstance(condition, str):
                ids: list[str] = []
                for variable in _condition_variables(condition):
                    ids.extend(backlinks_by_variable.get(variable, ()))
                if ids:
                    node["state_backlink_ids"] = sorted(set(ids))

        return {
            "schema_version": 1,
            "mode": "phase05_progressive",
            "status": "synthesized",
            "analysis_note": (
                "Phase 05 progressive story walk built from persisted parser facts; "
                "AI may add prose without changing this structure."
            ),
            "entry_label": self.entry_label,
            "stop_labels": sorted(self.stop_labels),
            "terminal_labels": dict(sorted(self.terminal_labels.items())),
            "counts": {
                "nodes": len(nodes),
                "edges": len(edges),
                "menus": sum(node["type"] == "choice" for node in nodes),
                "arms": sum(edge["kind"] == "choice" for edge in edges),
                "conditions": sum(node["type"] == "condition" for node in nodes),
                "effects": sum(node["type"] == "effect" for node in nodes),
                "corridors": sum(node["type"] == "corridor" for node in nodes),
            },
            "nodes": nodes,
            "edges": edges,
            "state_backlinks": backlinks,
        }

    def _index_labels(self) -> None:
        for parsed in self.parsed_sources:
            path = _text(parsed.get("path"), "parsed source path")
            if self.source_paths is not None and path not in self.source_paths:
                continue
            top_level = _list(parsed.get("top_level"), "parsed top_level")
            ordered: list[str] = []
            for raw in top_level:
                statement = _mapping(raw, "top-level statement")
                if statement.get("type") != "label":
                    continue
                name = _text(statement.get("name"), "label name")
                if name in self.labels:
                    raise ValueError(f"duplicate label {name!r}")
                self.labels[name] = statement
                self.label_paths[name] = path
                ordered.append(name)
            for index, name in enumerate(ordered):
                self.fallthrough[name] = ordered[index + 1] if index + 1 < len(ordered) else None

    def _label_node(self, name: str) -> str:
        existing = self._label_nodes.get(name)
        if existing is not None:
            return existing
        statement = self.labels[name]
        source = _source(statement)
        if name in self.stop_labels:
            kind = "rejoin"
        elif name in self.terminal_labels:
            kind = "terminal"
        else:
            kind = "label"
        title = self.terminal_labels.get(name) or self.label_titles.get(name) or _humanize(name)
        node_id = self._node(kind, source, title=title, label=name)
        self._label_nodes[name] = node_id
        return node_id

    def _boundary_node(self, label: str, title: str) -> str:
        source = _source(self.labels[label])
        return self._node("unresolved", source, title=title, label=label)

    def _build_sequence(self, raw_statements: Sequence[object], continuation: str) -> str:
        next_node = continuation
        pending_story: list[Mapping[str, object]] = []

        def flush() -> None:
            nonlocal next_node, pending_story
            if not pending_story:
                return
            source = _source(pending_story[0])
            last_source = _source(pending_story[-1])
            source["end_line"] = last_source["end_line"]
            lines = [_story_text(item) for item in pending_story]
            lines = [line for line in lines if line]
            corridor = self._node(
                "corridor",
                source,
                title="Story corridor",
                text="\n".join(lines),
                statement_count=len(pending_story),
            )
            self._edge(corridor, next_node, "next")
            next_node = corridor
            pending_story = []

        for raw in reversed(raw_statements):
            statement = _mapping(raw, "parsed statement")
            kind = statement.get("type")
            if kind == "simple":
                simple_kind = statement.get("kind")
                if simple_kind not in _TECHNICAL_SIMPLE_KINDS:
                    pending_story.insert(0, statement)
                continue
            if kind == "if" and _cosmetic_if(statement):
                continue
            if kind == "opaque" and _is_notification(statement):
                continue
            flush()
            next_node = self._build_statement(statement, next_node)
        flush()
        return next_node

    def _build_statement(self, statement: Mapping[str, object], continuation: str) -> str:
        kind = statement.get("type")
        source = _source(statement)
        if kind == "jump":
            target = statement.get("target")
            if isinstance(target, str) and target in self.labels:
                destination = self._label_node(target)
                node = self._node(
                    "destination",
                    source,
                    title=self.label_titles.get(target, _humanize(target)),
                )
                self._edge(node, destination, "jump", target_label=target)
                return node
            return self._node(
                "unresolved",
                source,
                title="Unresolved jump",
                target=target,
                expression=statement.get("expression"),
            )
        if kind == "menu":
            menu = self._node("choice", source, title="Choice")
            for order, raw_choice in enumerate(_list(statement.get("choices"), "menu choices"), 1):
                choice = _mapping(raw_choice, "menu choice")
                arm_entry = self._build_sequence(
                    _list(choice.get("body"), "choice body"), continuation
                )
                self._edge(
                    menu,
                    arm_entry,
                    "choice",
                    order=order,
                    caption=_text(choice.get("caption"), "choice caption"),
                    condition=choice.get("condition"),
                    evidence=_source(choice),
                )
            return menu
        if kind == "if":
            condition_node = self._node("condition", source, title="Condition")
            has_else = False
            conditions: list[str] = []
            branches = _list(statement.get("branches"), "if branches")
            for order, raw_branch in enumerate(branches, 1):
                branch = _mapping(raw_branch, "if branch")
                condition = branch.get("condition")
                has_else = has_else or condition is None
                if isinstance(condition, str):
                    conditions.append(condition)
                branch_entry = self._build_sequence(
                    _list(branch.get("body"), "if body"), continuation
                )
                self._edge(
                    condition_node,
                    branch_entry,
                    "condition",
                    order=order,
                    condition=condition,
                    evidence=_source(branch),
                )
            if not has_else:
                self._edge(
                    condition_node,
                    continuation,
                    "condition_false",
                    order=len(branches) + 1,
                    condition="not (" + " or ".join(conditions) + ")",
                )
            self.nodes[condition_node]["condition"] = " or ".join(conditions) or "else"
            return condition_node
        if kind == "opaque":
            assignment = _assignment(statement)
            if assignment is not None and (
                not self.state_variables or assignment[0] in self.state_variables
            ):
                variable, operator, expression = assignment
                effect = self._node(
                    "effect",
                    source,
                    title=f"{variable} {operator} {expression}",
                    variable=variable,
                    operator=operator,
                    expression=expression,
                )
                self._edge(effect, continuation, "next")
                return effect
            unresolved = self._node(
                "unresolved",
                source,
                title="Unsupported creator statement",
                text=statement.get("text"),
            )
            self._edge(unresolved, continuation, "next")
            return unresolved
        if kind == "label":
            name = statement.get("name")
            if isinstance(name, str) and name in self.labels:
                return self._label_node(name)
        unresolved = self._node(
            "unresolved",
            source,
            title=f"Unsupported {kind or 'statement'}",
            text=statement.get("text"),
        )
        self._edge(unresolved, continuation, "next")
        return unresolved

    def _state_backlinks(self, reachable: set[str]) -> list[dict[str, object]]:
        if not self.backlink_variables:
            return []
        active_labels = {
            str(node.get("label"))
            for node_id, node in self.nodes.items()
            if node_id in reachable and isinstance(node.get("label"), str)
        }
        result: list[dict[str, object]] = []
        for parsed in self.parsed_sources:
            path = _text(parsed.get("path"), "parsed source path")
            for raw in _list(parsed.get("top_level"), "parsed top_level"):
                label = _mapping(raw, "top-level statement")
                if label.get("type") != "label":
                    continue
                label_name = _text(label.get("name"), "label name")
                if label_name in active_labels:
                    continue
                for assignment, choice_path in _scan_assignments(
                    _list(label.get("body"), "label body"), ()
                ):
                    variable, operator, expression, source = assignment
                    if variable not in self.backlink_variables:
                        continue
                    item_id = f"backlink:{variable}:{path}:{source['start_line']}"
                    result.append(
                        {
                            "id": item_id,
                            "variable": variable,
                            "operator": operator,
                            "expression": expression,
                            "label": label_name,
                            "choice_path": list(choice_path),
                            "source": source,
                        }
                    )
        result.sort(
            key=lambda item: (
                str(item["variable"]),
                str(cast(Mapping[str, object], item["source"])["path"]),
                _integer(
                    cast(Mapping[str, object], item["source"])["start_line"],
                    "backlink source start line",
                ),
            )
        )
        return result

    def _node(self, kind: str, source: Mapping[str, object], **values: object) -> str:
        path = _text(source.get("path"), "source path")
        line = _integer(source.get("start_line"), "source start line")
        key = (kind, path, line)
        ordinal = self._node_ordinals[key]
        self._node_ordinals[key] += 1
        node_id = f"walk:{kind}:{path}:{line}:{ordinal}"
        if node_id not in self.nodes:
            self.nodes[node_id] = {"id": node_id, "type": kind, "source": dict(source), **values}
        return node_id

    def _edge(self, source: str, target: str, kind: str, **values: object) -> None:
        self.edges.append({"source": source, "target": target, "kind": kind, **values})

    def _reachable(self, entry: str) -> set[str]:
        outgoing: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            outgoing[str(edge["source"])].append(str(edge["target"]))
        pending = deque([entry])
        seen: set[str] = set()
        while pending:
            node_id = pending.popleft()
            if node_id in seen:
                continue
            seen.add(node_id)
            pending.extend(outgoing.get(node_id, ()))
        return seen


def _scan_assignments(
    raw_statements: Sequence[object], choice_path: tuple[str, ...]
) -> Iterable[tuple[tuple[str, str, str, dict[str, object]], tuple[str, ...]]]:
    for raw in raw_statements:
        statement = _mapping(raw, "parsed statement")
        assignment = _assignment(statement)
        if assignment is not None:
            yield (*assignment, _source(statement)), choice_path
        if statement.get("type") == "menu":
            for raw_choice in _list(statement.get("choices"), "menu choices"):
                choice = _mapping(raw_choice, "menu choice")
                caption = _text(choice.get("caption"), "choice caption")
                yield from _scan_assignments(
                    _list(choice.get("body"), "choice body"), (*choice_path, caption)
                )
        elif statement.get("type") == "if":
            for raw_branch in _list(statement.get("branches"), "if branches"):
                branch = _mapping(raw_branch, "if branch")
                yield from _scan_assignments(_list(branch.get("body"), "if body"), choice_path)


def _assignment(statement: Mapping[str, object]) -> tuple[str, str, str] | None:
    if statement.get("type") != "opaque":
        return None
    text = statement.get("text")
    if not isinstance(text, str):
        return None
    match = _ASSIGNMENT.fullmatch(text.strip())
    if match is None:
        return None
    return match.group("variable"), match.group("operator"), match.group("expression")


def _is_notification(statement: Mapping[str, object]) -> bool:
    return statement.get("type") == "opaque" and "renpy.notify(" in str(statement.get("text", ""))


def _cosmetic_if(statement: Mapping[str, object]) -> bool:
    if statement.get("type") != "if":
        return False
    leaves: list[Mapping[str, object]] = []
    for raw_branch in _list(statement.get("branches"), "if branches"):
        branch = _mapping(raw_branch, "if branch")
        leaves.extend(
            _mapping(raw, "if statement") for raw in _list(branch.get("body"), "if body")
        )
    return bool(leaves) and all(
        _is_notification(item)
        or (item.get("type") == "simple" and item.get("kind") in _TECHNICAL_SIMPLE_KINDS)
        for item in leaves
    )


def _condition_variables(condition: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            identifier
            for identifier in _IDENTIFIER.findall(condition)
            if identifier not in _IGNORED_IDENTIFIERS and not identifier.isdigit()
        )
    )


def _story_text(statement: Mapping[str, object]) -> str:
    raw = str(statement.get("text", "")).strip()
    match = _QUOTED_STORY.match(raw)
    if match is None:
        return raw
    try:
        value = ast.literal_eval(match.group("text"))
    except (SyntaxError, ValueError):
        return raw
    if not isinstance(value, str):
        return raw
    speaker = match.group("speaker")
    return f"{speaker}: {value}" if speaker else value


def _humanize(label: str) -> str:
    return " ".join(part for part in label.strip("_").replace("_clean", "").split("_") if part)


def _node_sort_key(node: Mapping[str, object]) -> tuple[str, int, str]:
    source = cast(Mapping[str, object], node["source"])
    return (
        str(source["path"]),
        _integer(source["start_line"], "node source start line"),
        str(node["id"]),
    )


def _source(statement: Mapping[str, object]) -> dict[str, object]:
    return dict(_mapping(statement.get("source"), "statement source"))


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be non-empty text")
    return value


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value
