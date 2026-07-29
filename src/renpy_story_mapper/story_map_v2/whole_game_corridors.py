"""Deterministic Phase 05 story-corridor packets over existing parser/graph facts.

This module does not solve control flow.  It collapses maximal linear runs between
the already-authoritative M01 graph controls, binds narrative statements back to
``parsed_source``, and uses M06 regions only to expose all demonstrated rejoin arms.
"""

from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict, deque
from collections.abc import Mapping, Sequence
from typing import cast

_CONTROL_KINDS = frozenset(
    {
        "label",
        "menu",
        "menu_choice",
        "if",
        "if_branch",
        "jump",
        "call",
        "return",
        "merge",
        "unresolved",
    }
)
_CORRIDOR_BOUNDARY_KINDS = _CONTROL_KINDS.union({"opaque"})
_ASSIGNMENT = re.compile(
    r"^\$\s*(?P<variable>[A-Za-z_]\w*)\s*"
    r"(?P<operator>\+=|-=|=)\s*(?P<expression>.+?)\s*$"
)
_QUOTED_STORY = re.compile(r"^(?:(?P<speaker>[A-Za-z_]\w*)\s+)?(?P<text>['\"].*)$")
_TEXT_TAG = re.compile(r"\{/?[^}]+\}")
_UI_HELPER = re.compile(
    r"\b(?:turn|switch|enable|disable)\b.*\bhints?\b.*"
    r"\b(?:settings|preferences)(?:\s+menu)?\b",
    re.IGNORECASE,
)


def build_whole_game_corridor_packets(
    parsed_sources: Sequence[Mapping[str, object]],
    graph: Mapping[str, object],
    control_flow: Mapping[str, object],
    *,
    authority_bindings: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Project whole-game packets without inventing boundaries or mechanics."""

    nodes = _indexed_nodes(graph)
    entry_label = _text(graph.get("entry_label"), "graph entry_label")
    entry_ids = [
        node_id
        for node_id, node in nodes.items()
        if node.get("kind") == "label" and node.get("label") == entry_label
    ]
    if len(entry_ids) != 1:
        raise ValueError(f"entry label {entry_label!r} must have exactly one graph node")

    reachable_ids = {
        node_id for node_id, node in nodes.items() if node.get("reachable_from_entry") is True
    }
    raw_edges = [_mapping(item, "graph edge") for item in _list(graph.get("edges"), "edges")]
    edges = [
        edge
        for edge in raw_edges
        if edge.get("source") in reachable_ids and edge.get("target") in reachable_ids
    ]
    outgoing, incoming = _adjacency(edges)
    flow_order, discovered_reachable = _flow_order(
        entry_ids[0], nodes, outgoing, reachable_ids
    )

    parsed_statements = _parsed_statement_index(parsed_sources)
    graph_statement_ids = {
        node_id for node_id in reachable_ids if nodes[node_id].get("kind") == "statement"
    }
    missing_parsed = sorted(
        node_id
        for node_id in graph_statement_ids
        if _source_key(nodes[node_id]) not in parsed_statements
    )
    if missing_parsed:
        raise ValueError(
            f"{len(missing_parsed)} reachable graph statements lack parsed_source bindings"
        )

    assignment_by_id = {
        node_id: assignment
        for node_id in reachable_ids
        if (assignment := _assignment(nodes[node_id])) is not None
    }
    boundary_ids = {
        node_id
        for node_id in reachable_ids
        if nodes[node_id].get("kind") in _CORRIDOR_BOUNDARY_KINDS
    }
    mechanics = [
        _project_mechanic(
            nodes[node_id],
            outgoing.get(node_id, ()),
            nodes,
            assignment_by_id.get(node_id),
        )
        for node_id in sorted(boundary_ids, key=lambda item: _node_order(item, nodes, flow_order))
    ]

    m06 = _M06Rejoins(control_flow, nodes)
    components, cyclic_components = _linear_components(
        reachable_ids.difference(boundary_ids),
        outgoing,
        incoming,
        nodes,
        flow_order,
    )
    packets: list[dict[str, object]] = []
    included_statement_ids: set[str] = set()
    filtered_statement_ids: set[str] = set()
    filtered_reasons: dict[str, str] = {}
    story_bearing_corridor_components = 0
    excluded_only_corridor_components = 0
    for component in components:
        raw_story_ids = [
            node_id for node_id in component if nodes[node_id].get("kind") == "statement"
        ]
        if raw_story_ids:
            story_bearing_corridor_components += 1
        story_ids: list[str] = []
        filtered_ids: list[str] = []
        story_lines: list[str] = []
        for node_id in raw_story_ids:
            parsed = parsed_statements[_source_key(nodes[node_id])]
            speaker, story_text = _story_parts(_text(parsed.get("text"), "story text"))
            reason = _helper_exclusion_reason(
                _text(nodes[node_id].get("label"), "story statement label"),
                speaker,
                story_text,
            )
            if reason is not None:
                filtered_ids.append(node_id)
                filtered_reasons[node_id] = reason
                continue
            story_ids.append(node_id)
            story_lines.append(f"{speaker}: {story_text}" if speaker else story_text)
        included_statement_ids.update(story_ids)
        filtered_statement_ids.update(filtered_ids)
        if not story_ids:
            if raw_story_ids:
                excluded_only_corridor_components += 1
            continue

        first_node = nodes[story_ids[0]]
        source = _component_source(raw_story_ids, nodes)
        corridor_id = f"corridor:{story_ids[0]}"
        incoming_controls = _nearest_boundaries(
            component[0],
            incoming,
            nodes,
            boundary_ids,
            reverse=True,
        )
        next_controls = _nearest_boundaries(
            component[-1],
            outgoing,
            nodes,
            boundary_ids,
            reverse=False,
        )
        incoming_rejoins = [
            m06.project_merge(control_id, incoming.get(control_id, ()))
            for control_id in incoming_controls
            if nodes[control_id].get("kind") == "merge"
        ]
        packets.append(
            {
                "corridor_id": corridor_id,
                "owning_label": _text(first_node.get("label"), "corridor label"),
                "source": source,
                "story_text": "\n".join(story_lines),
                "python_corridor": {
                    "node_ids": list(component),
                    "source_span": _component_source(component, nodes),
                    "narrative_statement_node_ids": story_ids,
                    "excluded_non_story_node_ids": filtered_ids,
                    "python_statement_count": len(raw_story_ids),
                    "narrative_statement_count": len(story_ids),
                    "technical_node_count": len(component) - len(raw_story_ids),
                },
                "incoming_control_points": [
                    _project_mechanic(
                        nodes[node_id],
                        outgoing.get(node_id, ()),
                        nodes,
                        assignment_by_id.get(node_id),
                    )
                    for node_id in incoming_controls
                ],
                "incoming_rejoins": incoming_rejoins,
                "next_control_points": [
                    _project_mechanic(
                        nodes[node_id],
                        outgoing.get(node_id, ()),
                        nodes,
                        assignment_by_id.get(node_id),
                    )
                    for node_id in next_controls
                ],
                "presentation_children": [],
            }
        )

    packets.sort(
        key=lambda packet: _node_order(
            _text(
                _mapping(packet.get("python_corridor"), "python corridor").get("node_ids")[0],  # type: ignore[index]
                "first corridor node id",
            ),
            nodes,
            flow_order,
        )
    )
    unaccounted_statements = graph_statement_ids.difference(
        included_statement_ids.union(filtered_statement_ids)
    )
    mechanic_counts = Counter(str(item["kind"]) for item in mechanics)
    filtered_reason_counts = Counter(filtered_reasons.values())
    incoming_rejoin_packets = 0
    incoming_rejoin_route_origins = 0
    for packet in packets:
        packet_rejoins = cast(list[dict[str, object]], packet["incoming_rejoins"])
        if packet_rejoins:
            incoming_rejoin_packets += 1
        for rejoin in packet_rejoins:
            incoming_rejoin_route_origins += len(
                cast(list[object], rejoin["route_origins"])
            )
    reachable_labels = {
        str(nodes[node_id]["label"])
        for node_id in reachable_ids
        if nodes[node_id].get("kind") == "label"
    }
    all_labels = {
        str(node["label"]) for node in nodes.values() if node.get("kind") == "label"
    }
    checks = {
        "all_reachable_statements_accounted_exactly_once": not unaccounted_statements
        and included_statement_ids.isdisjoint(filtered_statement_ids)
        and included_statement_ids.union(filtered_statement_ids) == graph_statement_ids,
        "parsed_source_bound_for_every_reachable_statement": not missing_parsed,
        "all_reachable_controls_and_effects_retained": len(mechanics) == len(boundary_ids),
        "all_graph_reachable_nodes_discovered": discovered_reachable == len(reachable_ids),
        "corridor_components_are_linear": cyclic_components == 0,
    }
    coverage_grade = "PASS" if all(checks.values()) else "FAIL"
    limitations = [
        "Static Python structure is retained; conditions are not evaluated.",
        "All statically reachable menu and condition arms remain possible.",
        "AI presentation children are intentionally empty in this export.",
        (
            "Packet array order is processing order only; the reader must place all branches "
            "before their shared continuation from Python control/rejoin facts."
        ),
    ]
    if mechanic_counts["unresolved"]:
        limitations.append(
            f"{mechanic_counts['unresolved']} reachable unresolved mechanics remain explicit."
        )
    return {
        "schema_version": 1,
        "mode": "phase05_whole_game_corridor_packets",
        "entry_label": entry_label,
        "coverage_grade": coverage_grade,
        "authority_bindings": dict(sorted((authority_bindings or {}).items())),
        "counts": {
            "packets": len(packets),
            "story_bearing_corridor_components": story_bearing_corridor_components,
            "excluded_only_corridor_components": excluded_only_corridor_components,
            "total_labels": len(all_labels),
            "reachable_labels": len(reachable_labels),
            "unreachable_labels": len(all_labels.difference(reachable_labels)),
            "reachable_graph_nodes": len(reachable_ids),
            "reachable_graph_edges": len(edges),
            "reachable_statement_nodes": len(graph_statement_ids),
            "included_narrative_statements": len(included_statement_ids),
            "excluded_non_story_statements": len(filtered_statement_ids),
            "filtered_statement_reasons": dict(sorted(filtered_reason_counts.items())),
            "accounted_statement_nodes": len(included_statement_ids)
            + len(filtered_statement_ids),
            "mechanics": len(mechanics),
            "state_effects": len(assignment_by_id),
            "incoming_rejoin_packets": incoming_rejoin_packets,
            "incoming_rejoin_route_origins": incoming_rejoin_route_origins,
            "cyclic_corridor_components": cyclic_components,
            "mechanic_kinds": dict(sorted(mechanic_counts.items())),
        },
        "coverage": {
            "checks": checks,
            "unaccounted_statement_node_ids": sorted(unaccounted_statements),
            "excluded_non_story_statements": [
                {
                    "node_id": node_id,
                    "source": _flat_source(nodes[node_id]),
                    "reason": filtered_reasons[node_id],
                }
                for node_id in sorted(
                    filtered_statement_ids, key=lambda item: _source_sort(nodes[item])
                )
            ],
        },
        "presentation_contract": {
            "semantic_beats_are_children": True,
            "mechanics_owner": "python",
            "packet_array_order": "processing_order_only",
            "reader_order_rule": (
                "Use Python control and rejoin relationships; place every branch before its "
                "shared continuation."
            ),
            "allowed_ai_fields": ["title", "summary", "detail", "presentation_children"],
            "ai_may_not_add": ["choices", "conditions", "edges", "effects", "rejoins"],
        },
        "mechanics": mechanics,
        "packets": packets,
        "limitations": limitations,
    }


class _M06Rejoins:
    def __init__(
        self,
        control_flow: Mapping[str, object],
        graph_nodes: Mapping[str, Mapping[str, object]],
    ) -> None:
        self.graph_nodes = graph_nodes
        self.arms = {
            _text(arm.get("id"), "M06 arm id"): arm
            for item in _list(control_flow.get("arms"), "M06 arms")
            if (arm := _mapping(item, "M06 arm"))
        }
        self.regions = {
            _text(region.get("id"), "M06 region id"): region
            for item in _list(control_flow.get("regions"), "M06 regions")
            if (region := _mapping(item, "M06 region"))
        }
        self.regions_by_merge: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        self.children: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        for region in self.regions.values():
            merge_id = region.get("merge_node_id")
            if isinstance(merge_id, str):
                self.regions_by_merge[merge_id].append(region)
            parent_id = region.get("parent_region_id")
            if isinstance(parent_id, str):
                self.children[parent_id].append(region)
        self.owners: dict[str, set[str]] = defaultdict(set)
        for item in _list(control_flow.get("ownership"), "M06 ownership"):
            ownership = _mapping(item, "M06 ownership item")
            arm_id = ownership.get("arm_id")
            if isinstance(arm_id, str) and arm_id:
                self.owners[_text(ownership.get("node_id"), "owned node id")].add(arm_id)

    def project_merge(
        self,
        merge_id: str,
        direct_edges: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        regions = sorted(
            self.regions_by_merge.get(merge_id, ()),
            key=lambda item: _text(item.get("id"), "region id"),
        )
        origins: list[dict[str, object]] = []
        for region in regions:
            origins.extend(self._leaf_origins(region, ()))
        unique_origins = {
            (
                str(item["arm_id"]),
                tuple(cast(list[str], item["region_lineage"])),
            ): item
            for item in origins
        }
        return {
            "merge": _project_node_fact(self.graph_nodes[merge_id]),
            "direct_origins": [
                {
                    "edge_kind": _text(edge.get("kind"), "incoming merge edge kind"),
                    "origin": _project_node_fact(
                        self.graph_nodes[_text(edge.get("source"), "incoming merge source")]
                    ),
                }
                for edge in sorted(
                    direct_edges,
                    key=lambda item: (
                        _text(item.get("kind"), "incoming edge kind"),
                        _source_sort(
                            self.graph_nodes[
                                _text(item.get("source"), "incoming edge source")
                            ]
                        ),
                    ),
                )
            ],
            "route_origins": [unique_origins[key] for key in sorted(unique_origins)],
        }

    def _leaf_origins(
        self,
        region: Mapping[str, object],
        lineage: tuple[str, ...],
    ) -> list[dict[str, object]]:
        region_id = _text(region.get("id"), "region id")
        next_lineage = (*lineage, region_id)
        result: list[dict[str, object]] = []
        for arm_id in sorted(
            _text(item, "region arm id")
            for item in _list(region.get("arm_ids"), "region arm ids")
        ):
            nested = [
                child
                for child in self.children.get(region_id, ())
                if arm_id in self._parent_owners(child)
            ]
            if nested:
                for child in sorted(nested, key=lambda item: _text(item.get("id"), "child region")):
                    result.extend(self._leaf_origins(child, next_lineage))
                continue
            arm = self.arms[arm_id]
            entry_id = _text(arm.get("entry_node_id"), "arm entry node")
            result.append(
                {
                    "arm_id": arm_id,
                    "region_lineage": list(next_lineage),
                    "origin": _project_node_fact(self.graph_nodes[entry_id]),
                    "state_reads": _state_facts(arm.get("state_reads"), "arm state reads"),
                    "state_writes": _state_facts(
                        arm.get("state_writes"), "arm state writes"
                    ),
                    "unresolved": bool(arm.get("unresolved")),
                }
            )
        return result

    def _parent_owners(self, region: Mapping[str, object]) -> set[str]:
        result = set(
            self.owners.get(_text(region.get("split_node_id"), "child split node"), set())
        )
        merge_id = region.get("merge_node_id")
        if isinstance(merge_id, str):
            result.update(self.owners.get(merge_id, set()))
        return result


def _indexed_nodes(graph: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for item in _list(graph.get("nodes"), "graph nodes"):
        node = _mapping(item, "graph node")
        node_id = _text(node.get("id"), "graph node id")
        if node_id in result:
            raise ValueError(f"duplicate graph node id {node_id!r}")
        result[node_id] = node
    return result


def _adjacency(
    edges: Sequence[Mapping[str, object]],
) -> tuple[dict[str, list[Mapping[str, object]]], dict[str, list[Mapping[str, object]]]]:
    outgoing: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    incoming: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for edge in edges:
        outgoing[_text(edge.get("source"), "edge source")].append(edge)
        incoming[_text(edge.get("target"), "edge target")].append(edge)
    return outgoing, incoming


def _flow_order(
    entry_id: str,
    nodes: Mapping[str, Mapping[str, object]],
    outgoing: Mapping[str, Sequence[Mapping[str, object]]],
    reachable_ids: set[str],
) -> tuple[dict[str, int], int]:
    pending = deque([entry_id])
    order: dict[str, int] = {}
    while pending:
        node_id = pending.popleft()
        if node_id in order:
            continue
        order[node_id] = len(order)
        edges = sorted(outgoing.get(node_id, ()), key=lambda item: _edge_order(item, nodes))
        pending.extend(_text(edge.get("target"), "flow target") for edge in edges)
    discovered_reachable = len(order)
    for node_id in sorted(
        reachable_ids.difference(order), key=lambda item: _source_sort(nodes[item])
    ):
        order[node_id] = len(order)
    return order, discovered_reachable


def _state_facts(value: object, name: str) -> list[dict[str, object]]:
    facts = [dict(_mapping(item, name)) for item in _list(value, name)]
    facts.sort(
        key=lambda item: (
            str(item.get("variable", "")),
            str(item.get("expression", "")),
            str(item.get("node_id", "")),
        )
    )
    return facts


def _linear_components(
    transparent_ids: set[str],
    outgoing: Mapping[str, Sequence[Mapping[str, object]]],
    incoming: Mapping[str, Sequence[Mapping[str, object]]],
    nodes: Mapping[str, Mapping[str, object]],
    flow_order: Mapping[str, int],
) -> tuple[list[tuple[str, ...]], int]:
    starts: list[str] = []
    for node_id in transparent_ids:
        predecessors = incoming.get(node_id, ())
        if len(predecessors) != 1:
            starts.append(node_id)
            continue
        predecessor = _text(predecessors[0].get("source"), "corridor predecessor")
        if predecessor not in transparent_ids or len(outgoing.get(predecessor, ())) != 1:
            starts.append(node_id)
    starts.sort(key=lambda item: _node_order(item, nodes, flow_order))

    seen: set[str] = set()
    components: list[tuple[str, ...]] = []

    def follow(start: str) -> tuple[str, ...]:
        result: list[str] = []
        current = start
        while current not in seen:
            seen.add(current)
            result.append(current)
            successors = outgoing.get(current, ())
            if len(successors) != 1:
                break
            target = _text(successors[0].get("target"), "corridor successor")
            if target not in transparent_ids or len(incoming.get(target, ())) != 1:
                break
            current = target
        return tuple(result)

    for start in starts:
        if start not in seen:
            components.append(follow(start))
    cyclic_components = 0
    for start in sorted(
        transparent_ids.difference(seen), key=lambda item: _node_order(item, nodes, flow_order)
    ):
        if start in seen:
            continue
        cyclic_components += 1
        components.append(follow(start))
    return components, cyclic_components


def _nearest_boundaries(
    start: str,
    adjacency: Mapping[str, Sequence[Mapping[str, object]]],
    nodes: Mapping[str, Mapping[str, object]],
    boundary_ids: set[str],
    *,
    reverse: bool,
) -> list[str]:
    pending = deque(
        _text(edge.get("source" if reverse else "target"), "adjacent node")
        for edge in adjacency.get(start, ())
    )
    seen: set[str] = set()
    found: set[str] = set()
    while pending:
        node_id = pending.popleft()
        if node_id in seen:
            continue
        seen.add(node_id)
        if node_id in boundary_ids:
            found.add(node_id)
            continue
        pending.extend(
            _text(edge.get("source" if reverse else "target"), "traversed node")
            for edge in adjacency.get(node_id, ())
        )
    return sorted(found, key=lambda item: _source_sort(nodes[item]))


def _project_mechanic(
    node: Mapping[str, object],
    outgoing: Sequence[Mapping[str, object]],
    nodes: Mapping[str, Mapping[str, object]],
    assignment: tuple[str, str, str] | None,
) -> dict[str, object]:
    result = _project_node_fact(node)
    if assignment is not None:
        variable, operator, expression = assignment
        result["kind"] = "effect"
        result["state_effect"] = {
            "variable": variable,
            "operator": operator,
            "expression": expression,
        }
    result["arms"] = [
        {
            "edge_kind": _text(edge.get("kind"), "mechanic edge kind"),
            "metadata": dict(_mapping(edge.get("metadata", {}), "mechanic edge metadata")),
            "target": _project_node_fact(
                nodes[_text(edge.get("target"), "mechanic edge target")]
            ),
        }
        for edge in sorted(outgoing, key=lambda item: _edge_order(item, nodes))
        if edge.get("kind") != "fallthrough"
    ]
    return result


def _project_node_fact(node: Mapping[str, object]) -> dict[str, object]:
    return {
        "node_id": _text(node.get("id"), "node id"),
        "kind": _text(node.get("kind"), "node kind"),
        "label": _text(node.get("label"), "node label"),
        "source_text": _text(node.get("source_text"), "node source text"),
        "source": _flat_source(node),
        "metadata": dict(_mapping(node.get("metadata", {}), "node metadata")),
    }


def _parsed_statement_index(
    parsed_sources: Sequence[Mapping[str, object]],
) -> dict[tuple[str, int, int, int, int], Mapping[str, object]]:
    result: dict[tuple[str, int, int, int, int], Mapping[str, object]] = {}

    def visit(statement: Mapping[str, object]) -> None:
        if statement.get("type") == "simple" and statement.get("kind") == "statement":
            key = _flat_source_key(_mapping(statement.get("source"), "parsed source"))
            if key in result:
                raise ValueError(f"duplicate parsed statement source {key!r}")
            result[key] = statement
        if statement.get("type") == "label":
            children = _list(statement.get("body"), "label body")
        elif statement.get("type") == "menu":
            children = []
            for item in _list(statement.get("choices"), "menu choices"):
                choice = _mapping(item, "menu choice")
                children.extend(_list(choice.get("body"), "menu choice body"))
        elif statement.get("type") == "if":
            children = []
            for item in _list(statement.get("branches"), "if branches"):
                branch = _mapping(item, "if branch")
                children.extend(_list(branch.get("body"), "if branch body"))
        else:
            children = []
        for child in children:
            visit(_mapping(child, "parsed child statement"))

    for parsed in parsed_sources:
        for item in _list(parsed.get("top_level"), "parsed top_level"):
            visit(_mapping(item, "parsed top-level statement"))
    return result


def _story_parts(raw: str) -> tuple[str | None, str]:
    text = raw.strip()
    match = _QUOTED_STORY.match(text)
    if match is None:
        return None, text
    try:
        value = ast.literal_eval(match.group("text"))
    except (SyntaxError, ValueError):
        return match.group("speaker"), text
    if not isinstance(value, str):
        return match.group("speaker"), text
    return match.group("speaker"), value


def _helper_exclusion_reason(
    label: str,
    speaker: str | None,
    story_text: str,
) -> str | None:
    plain = _TEXT_TAG.sub("", story_text).strip()
    if speaker is None and plain == "Are you 18 years or older?":
        return "adult_entry_prompt"
    if speaker is None and plain == "Sorry! You cannot play this game.":
        return "adult_entry_refusal"
    if speaker in {None, "narrator"} and plain == "You should save now":
        return "checkpoint_save_prompt"
    if (
        label == "credits"
        and speaker == "centered"
        and plain
        == (
            "A special thank you to our treasured patrons, without whom this game would not be "
            "possible. Here are some of them....."
        )
    ):
        return "credits_patron_thank_you"
    if speaker is None and _UI_HELPER.search(plain) is not None:
        return "speakerless_hint_settings_instruction"
    return None


def _assignment(node: Mapping[str, object]) -> tuple[str, str, str] | None:
    if node.get("kind") != "opaque":
        return None
    match = _ASSIGNMENT.fullmatch(str(node.get("source_text", "")).strip())
    if match is None:
        return None
    return match.group("variable"), match.group("operator"), match.group("expression")


def _component_source(
    component: Sequence[str], nodes: Mapping[str, Mapping[str, object]]
) -> dict[str, object]:
    first = _mapping(nodes[component[0]].get("source"), "first corridor source")
    last = _mapping(nodes[component[-1]].get("source"), "last corridor source")
    first_path = _text(first.get("path"), "first corridor path")
    if first_path != _text(last.get("path"), "last corridor path"):
        raise ValueError("a Python corridor cannot cross source files without a control boundary")
    start = _mapping(first.get("start"), "corridor start")
    end = _mapping(last.get("end"), "corridor end")
    return {
        "path": first_path,
        "start_line": _integer(start.get("line"), "corridor start line"),
        "start_column": _integer(start.get("column"), "corridor start column"),
        "end_line": _integer(end.get("line"), "corridor end line"),
        "end_column": _integer(end.get("column"), "corridor end column"),
    }


def _flat_source(node: Mapping[str, object]) -> dict[str, object]:
    source = _mapping(node.get("source"), "node source")
    start = _mapping(source.get("start"), "node source start")
    end = _mapping(source.get("end"), "node source end")
    return {
        "path": _text(source.get("path"), "node source path"),
        "start_line": _integer(start.get("line"), "node start line"),
        "start_column": _integer(start.get("column"), "node start column"),
        "end_line": _integer(end.get("line"), "node end line"),
        "end_column": _integer(end.get("column"), "node end column"),
    }


def _source_key(node: Mapping[str, object]) -> tuple[str, int, int, int, int]:
    return _flat_source_key(_flat_source(node))


def _flat_source_key(source: Mapping[str, object]) -> tuple[str, int, int, int, int]:
    return (
        _text(source.get("path"), "source path"),
        _integer(source.get("start_line"), "source start line"),
        _integer(source.get("start_column"), "source start column"),
        _integer(source.get("end_line"), "source end line"),
        _integer(source.get("end_column"), "source end column"),
    )


def _source_sort(node: Mapping[str, object]) -> tuple[str, int, int, str]:
    source = _flat_source(node)
    return (
        str(source["path"]),
        cast(int, source["start_line"]),
        cast(int, source["start_column"]),
        _text(node.get("id"), "source-sort node id"),
    )


def _node_order(
    node_id: str,
    nodes: Mapping[str, Mapping[str, object]],
    flow_order: Mapping[str, int],
) -> tuple[int, str, int, int, str]:
    source = _source_sort(nodes[node_id])
    return (flow_order[node_id], source[0], source[1], source[2], source[3])


def _edge_order(
    edge: Mapping[str, object], nodes: Mapping[str, Mapping[str, object]]
) -> tuple[int, int, str, tuple[str, int, int, str]]:
    kind = _text(edge.get("kind"), "edge kind")
    metadata = _mapping(edge.get("metadata", {}), "edge metadata")
    ordinal = metadata.get("choice_index", metadata.get("branch_index", -1))
    return (
        {"label_entry": 0, "menu_choice": 1, "condition": 1, "condition_false": 2}.get(
            kind, 3
        ),
        ordinal if isinstance(ordinal, int) else -1,
        kind,
        _source_sort(nodes[_text(edge.get("target"), "edge target")]),
    )


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
