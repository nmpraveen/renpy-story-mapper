"""Thin Phase 05 whole-game projection over existing authoritative graph facts."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping
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
_DIRECT_ASSIGNMENT = re.compile(r"^\$\s*[A-Za-z_]\w*\s*(?:\+=|-=|=)")


def build_whole_game_skeleton(
    graph: Mapping[str, object],
    *,
    control_flow: Mapping[str, object] | None = None,
    parser_coverage: Mapping[str, object] | None = None,
    authority_bindings: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Project compact coverage and structure without rebuilding control flow."""

    entry_label = _text(graph.get("entry_label"), "graph entry_label")
    raw_nodes = _list(graph.get("nodes"), "graph nodes")
    nodes = [_mapping(item, "graph node") for item in raw_nodes]
    nodes_by_id: dict[str, Mapping[str, object]] = {}
    for node in nodes:
        node_id = _text(node.get("id"), "graph node id")
        if node_id in nodes_by_id:
            raise ValueError(f"duplicate graph node id {node_id!r}")
        nodes_by_id[node_id] = node

    raw_edges = _list(graph.get("edges"), "graph edges")
    edges = [_mapping(item, "graph edge") for item in raw_edges]
    for edge in edges:
        source = _text(edge.get("source"), "graph edge source")
        target = _text(edge.get("target"), "graph edge target")
        if source not in nodes_by_id or target not in nodes_by_id:
            raise ValueError("graph edge references an unknown node")

    graph_counts = _mapping(graph.get("counts"), "graph counts")
    label_nodes = [node for node in nodes if node.get("kind") == "label"]
    labels_by_name: dict[str, Mapping[str, object]] = {}
    for node in label_nodes:
        label = _text(node.get("label"), "label node label")
        if label in labels_by_name:
            raise ValueError(f"duplicate graph label {label!r}")
        labels_by_name[label] = node

    declared_reachable = {
        _text(item, "reachable label")
        for item in _list(graph.get("reachable_labels"), "reachable labels")
    }
    observed_reachable = {
        label
        for label, node in labels_by_name.items()
        if node.get("reachable_from_entry") is True
    }
    all_labels = set(labels_by_name)
    unreachable = all_labels.difference(observed_reachable)

    checks = {
        "entry_label_exists": entry_label in all_labels,
        "entry_label_is_reachable": entry_label in observed_reachable,
        "node_count_matches": _integer(graph_counts.get("nodes"), "graph node count")
        == len(nodes),
        "edge_count_matches": _integer(graph_counts.get("edges"), "graph edge count")
        == len(edges),
        "label_count_matches": _integer(
            graph_counts.get("labels_in_scope"), "graph labels_in_scope"
        )
        == len(all_labels),
        "reachable_label_count_matches": _integer(
            graph_counts.get("reachable_labels"), "graph reachable_labels count"
        )
        == len(observed_reachable),
        "reachable_label_set_matches": declared_reachable == observed_reachable,
        "every_label_accounted_for": observed_reachable.isdisjoint(unreachable)
        and observed_reachable.union(unreachable) == all_labels,
    }
    label_accounting_grade = "PASS" if all(checks.values()) else "FAIL"

    reachable_nodes = [node for node in nodes if node.get("reachable_from_entry") is True]
    reachable_ids = {_text(node.get("id"), "reachable node id") for node in reachable_nodes}
    reachable_edges = [
        edge
        for edge in edges
        if edge.get("source") in reachable_ids and edge.get("target") in reachable_ids
    ]
    total_node_kinds = Counter(_text(node.get("kind"), "graph node kind") for node in nodes)
    reachable_node_kinds = Counter(
        _text(node.get("kind"), "reachable graph node kind") for node in reachable_nodes
    )
    total_edge_kinds = Counter(_text(edge.get("kind"), "graph edge kind") for edge in edges)
    reachable_edge_kinds = Counter(
        _text(edge.get("kind"), "reachable graph edge kind") for edge in reachable_edges
    )

    unresolved_nodes = sorted(
        (node for node in reachable_nodes if node.get("kind") == "unresolved"),
        key=_node_sort_key,
    )
    unresolved_facts = [_project_node(node) for node in unresolved_nodes]
    checks["reachable_unresolved_count_matches"] = _integer(
        graph_counts.get("unresolved"), "graph unresolved count"
    ) == len(unresolved_facts)
    unresolved_reason_counts = Counter(
        str(_mapping(node.get("metadata", {}), "unresolved metadata").get("reason", "unknown"))
        for node in unresolved_nodes
    )

    controls = sorted(
        (node for node in reachable_nodes if node.get("kind") in _CONTROL_KINDS),
        key=_node_sort_key,
    )
    direct_assignments = sorted(
        (
            node
            for node in reachable_nodes
            if node.get("kind") == "opaque"
            and _DIRECT_ASSIGNMENT.match(str(node.get("source_text", "")))
        ),
        key=_node_sort_key,
    )
    nodes_by_label: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for node in nodes:
        raw_label = node.get("label")
        if isinstance(raw_label, str):
            nodes_by_label[raw_label].append(node)

    label_skeleton = []
    for label in sorted(all_labels):
        label_node = labels_by_name[label]
        label_members = nodes_by_label[label]
        member_counts = Counter(
            _text(node.get("kind"), "label member kind") for node in label_members
        )
        label_skeleton.append(
            {
                "label": label,
                "reachable_from_entry": label in observed_reachable,
                "source": dict(_mapping(label_node.get("source"), "label source")),
                "node_kind_counts": dict(sorted(member_counts.items())),
            }
        )

    label_transition_keys: set[tuple[str, str, str]] = set()
    for edge in reachable_edges:
        source_id = _text(edge.get("source"), "reachable edge source")
        target_id = _text(edge.get("target"), "reachable edge target")
        source_label = nodes_by_id[source_id].get("label")
        target_label = nodes_by_id[target_id].get("label")
        if not isinstance(source_label, str) or not isinstance(target_label, str):
            continue
        if source_label == target_label:
            continue
        label_transition_keys.add(
            (
                source_label,
                target_label,
                _text(edge.get("kind"), "label edge kind"),
            )
        )
    label_transitions = [
        {
            "source_label": source_label,
            "target_label": target_label,
            "transfer_kind": transfer_kind,
        }
        for source_label, target_label, transfer_kind in sorted(label_transition_keys)
    ]

    control_flow_summary = _control_flow_summary(control_flow, nodes_by_id)
    story_coverage_grade = "PASS" if all(checks.values()) else "FAIL"
    resolution_state = "partial" if unresolved_facts else "complete"
    parser_extraction = _parser_extraction_summary(parser_coverage)
    limitations = [
        "Static structure only; expressions and menu conditions are preserved but not evaluated.",
        "All menu and condition arms are conservatively included as statically selectable.",
        "AI prose and reader redesign are intentionally absent from this artifact.",
    ]
    if unresolved_facts:
        limitations.append(
            f"{len(unresolved_facts)} reachable unresolved graph facts remain explicit."
        )
    if control_flow_summary["diagnostics"]:
        limitations.append(
            "Existing control-flow diagnostics are retained; no new loop or region claims are made."
        )

    return {
        "mode": "phase05_whole_game_structure",
        "entry_label": entry_label,
        "parser_extraction_grade": parser_extraction["grade"],
        "label_accounting_grade": label_accounting_grade,
        "story_coverage_grade": story_coverage_grade,
        "resolution_state": resolution_state,
        "parser_extraction": parser_extraction,
        "coverage": {
            "checks": checks,
            "counts": {
                "total_parser_labels": len(all_labels),
                "reached_labels": len(observed_reachable),
                "unreachable_labels": len(unreachable),
                "accounted_labels": len(observed_reachable) + len(unreachable),
                "unresolved_mechanics": len(unresolved_facts),
            },
            "reached_labels": sorted(observed_reachable),
            "unreachable_labels": [
                {
                    "label": label,
                    "reason": "not_statically_reachable_from_entry",
                    "source": dict(
                        _mapping(labels_by_name[label].get("source"), "unreachable label source")
                    ),
                }
                for label in sorted(unreachable)
            ],
            "unresolved_facts": unresolved_facts,
            "unresolved_reason_counts": dict(sorted(unresolved_reason_counts.items())),
        },
        "counts": {
            "nodes": len(nodes),
            "reachable_nodes": len(reachable_nodes),
            "edges": len(edges),
            "reachable_edges": len(reachable_edges),
            "control_nodes": len(controls),
            "non_control_nodes": len(reachable_nodes) - len(controls),
            "story_statement_nodes": reachable_node_kinds["statement"]
            + reachable_node_kinds["scene"],
            "direct_state_changes": len(direct_assignments),
            "menus": reachable_node_kinds["menu"],
            "menu_arms": reachable_node_kinds["menu_choice"],
            "conditions": reachable_node_kinds["if"],
            "condition_arms": reachable_node_kinds["if_branch"],
            "jumps": reachable_node_kinds["jump"],
            "calls": reachable_node_kinds["call"],
            "returns": reachable_edge_kinds["return"],
            "demonstrated_rejoins": reachable_node_kinds["merge"],
            "unresolved": reachable_node_kinds["unresolved"],
            **cast(dict[str, int], control_flow_summary["counts"]),
        },
        "node_kind_counts": {
            "total": dict(sorted(total_node_kinds.items())),
            "reachable": dict(sorted(reachable_node_kinds.items())),
        },
        "edge_kind_counts": {
            "total": dict(sorted(total_edge_kinds.items())),
            "reachable": dict(sorted(reachable_edge_kinds.items())),
        },
        "skeleton": {
            "labels": label_skeleton,
            "label_transitions": label_transitions,
            "loops": control_flow_summary["loops"],
            "terminals": control_flow_summary["terminals"],
        },
        "control_flow_diagnostics": control_flow_summary["diagnostics"],
        "authority_bindings": dict(sorted((authority_bindings or {}).items())),
        "limitations": limitations,
    }


def _parser_extraction_summary(
    parser_coverage: Mapping[str, object] | None,
) -> dict[str, object]:
    if parser_coverage is None:
        return {"grade": "UNVERIFIED", "reason": "retained parser coverage audit not supplied"}
    deterministic = _mapping(
        parser_coverage.get("deterministic"), "parser coverage deterministic result"
    )
    return {
        "grade": _text(deterministic.get("grade"), "parser extraction grade"),
        "python_labels": _integer(deterministic.get("python_labels"), "python label count"),
        "renpy_labels": _integer(deterministic.get("renpy_labels"), "Ren'Py label count"),
        "matched_python_labels": _integer(
            deterministic.get("matched_python_labels"), "matched Python label count"
        ),
        "compiler_internal_labels": _integer(
            deterministic.get("compiler_internal_labels"), "compiler-internal label count"
        ),
        "substantive_missing_labels": len(
            _list(
                deterministic.get("canonical_substantive_labels_missing_from_python"),
                "substantive missing labels",
            )
        ),
        "missing_python_nodes": _integer(
            deterministic.get("missing_python_node_count"), "missing Python node count"
        ),
    }


def _control_flow_summary(
    control_flow: Mapping[str, object] | None,
    nodes_by_id: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    if control_flow is None:
        return {
            "counts": {
                "route_arms": 0,
                "loop_components": 0,
                "terminals": 0,
            },
            "loops": [],
            "terminals": [],
            "diagnostics": [],
        }

    arms = _list(control_flow.get("arms"), "control-flow arms")
    raw_loops = _list(control_flow.get("loops"), "control-flow loops")
    raw_terminals = _list(control_flow.get("terminals"), "control-flow terminals")
    raw_diagnostics = _list(control_flow.get("diagnostics"), "control-flow diagnostics")
    loops: list[dict[str, object]] = []
    for raw_loop in raw_loops:
        loop = _mapping(raw_loop, "control-flow loop")
        node_ids = [
            _text(item, "loop node id")
            for item in _list(loop.get("node_ids"), "loop nodes")
        ]
        entry_ids = [
            _text(item, "loop entry node id")
            for item in _list(loop.get("entry_node_ids"), "loop entry nodes")
        ]
        labels = sorted(
            {
                str(nodes_by_id[node_id]["label"])
                for node_id in node_ids
                if node_id in nodes_by_id and isinstance(nodes_by_id[node_id].get("label"), str)
            }
        )
        loops.append(
            {
                "id": _text(loop.get("id"), "loop id"),
                "irreducible": bool(loop.get("irreducible")),
                "self_loop": bool(loop.get("self_loop")),
                "node_count": len(node_ids),
                "labels": labels,
                "entry_node_ids": sorted(entry_ids),
                "back_edge_count": len(_list(loop.get("back_edge_ids"), "loop back edges")),
                "exit_edge_count": len(_list(loop.get("exit_edge_ids"), "loop exit edges")),
            }
        )
    loops.sort(key=lambda item: str(item["id"]))

    terminals: list[dict[str, object]] = []
    for raw_terminal in raw_terminals:
        terminal = _mapping(raw_terminal, "control-flow terminal")
        node_id = _text(terminal.get("node_id"), "terminal node id")
        node = nodes_by_id.get(node_id)
        terminals.append(
            {
                "node_id": node_id,
                "kind": _text(terminal.get("kind"), "terminal kind"),
                "label": node.get("label") if node is not None else None,
                "source": (
                    dict(_mapping(node.get("source"), "terminal source"))
                    if node is not None and isinstance(node.get("source"), dict)
                    else None
                ),
            }
        )
    terminals.sort(key=lambda item: (str(item["kind"]), str(item["node_id"])))

    diagnostics = []
    for raw_diagnostic in raw_diagnostics:
        diagnostic = _mapping(raw_diagnostic, "control-flow diagnostic")
        diagnostics.append(
            {
                "id": _text(diagnostic.get("id"), "diagnostic id"),
                "kind": _text(diagnostic.get("kind"), "diagnostic kind"),
                "message": _text(diagnostic.get("message"), "diagnostic message"),
                "node_count": len(
                    _list(diagnostic.get("node_ids", []), "diagnostic node ids")
                ),
            }
        )
    diagnostics.sort(key=lambda item: (str(item["kind"]), str(item["id"])))
    return {
        "counts": {
            "route_arms": len(arms),
            "loop_components": len(loops),
            "terminals": len(terminals),
        },
        "loops": loops,
        "terminals": terminals,
        "diagnostics": diagnostics,
    }


def _project_node(node: Mapping[str, object]) -> dict[str, object]:
    return {
        key: node[key]
        for key in ("id", "kind", "label", "source", "source_text", "metadata")
        if key in node
    }


def _node_sort_key(node: Mapping[str, object]) -> tuple[str, int, int, str]:
    source = _mapping(node.get("source"), "node source")
    start = _mapping(source.get("start"), "node source start")
    return (
        _text(source.get("path"), "node source path"),
        _integer(start.get("line"), "node source line"),
        _integer(start.get("column"), "node source column"),
        _text(node.get("id"), "node id"),
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
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
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value
