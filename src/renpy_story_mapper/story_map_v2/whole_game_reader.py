"""Whole-game reader assembly over Phase 05 Python facts and approved AI prose."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from typing import cast

from renpy_story_mapper.story_map_v2.progressive_story import PHASE05_PROGRESSIVE_MARKER

WHOLE_GAME_READER_MARKER = f"{PHASE05_PROGRESSIVE_MARKER}: whole-game reader"
_CONTROL_KINDS = frozenset({"menu", "if"})
_UNNAMED_ROUTE = "Unnamed story route"
_UNRESOLVED_DESTINATION = "Unresolved destination"
_MACHINE_IDENTIFIER = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b")


def build_whole_game_reader_page(
    graph: Mapping[str, object],
    control_flow: Mapping[str, object],
    skeleton: Mapping[str, object],
    corridors: Mapping[str, object],
    summaries: Mapping[str, object],
    *,
    name_overrides: Mapping[str, object] | None = None,
    name_inventory: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Attach corridor prose to its Python-owned label continuation or control arm."""

    _validate_inputs(graph, skeleton, corridors, summaries)
    nodes = _index(graph, "nodes", "id")
    edges = [_mapping(item, "graph edge") for item in _list(graph.get("edges"), "edges")]
    flow_order = _flow_order(graph, nodes, edges)
    regions = _index(control_flow, "regions", "id")
    arms = _index(control_flow, "arms", "id")
    region_depth = _region_depths(regions)
    regions_by_split = {
        _text(region.get("split_node_id"), "region split"): region
        for region in regions.values()
        if region.get("split_node_id") in nodes
        and nodes[cast(str, region["split_node_id"])].get("kind") in _CONTROL_KINDS
    }
    secondary_controls = {
        control_id
        for control_id in regions_by_split
        if _secondary_control(control_id, nodes, regions_by_split, arms)
    }
    ownership: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for raw in _list(control_flow.get("ownership"), "ownership"):
        item = _mapping(raw, "ownership item")
        if not isinstance(item.get("arm_id"), str) or not item.get("arm_id"):
            continue
        ownership[_text(item.get("node_id"), "owned node")].append(
            (
                _text(item.get("region_id"), "ownership region"),
                _text(item.get("arm_id"), "ownership arm"),
            )
        )
    for region_id, region in regions.items():
        split_id = region.get("split_node_id")
        if not isinstance(split_id, str) or split_id not in nodes:
            continue
        if nodes[split_id].get("kind") not in _CONTROL_KINDS:
            continue
        for raw_arm_id in _list(region.get("arm_ids"), "region arms"):
            arm_id = _text(raw_arm_id, "region arm")
            for raw_node_id in _list(arms[arm_id].get("node_ids"), "arm nodes"):
                ownership[_text(raw_node_id, "arm member")].append((region_id, arm_id))

    mechanics = {
        _text(item.get("node_id"), "mechanic id"): item
        for raw in _list(corridors.get("mechanics"), "mechanics")
        for item in (_mapping(raw, "mechanic"),)
    }
    results = {
        _text(item.get("corridor_id"), "summary corridor id"): item
        for raw in _list(summaries.get("results"), "summary results")
        for item in (_mapping(raw, "summary result"),)
    }
    excluded = {
        _text(_mapping(raw, "reader exclusion").get("corridor_id"), "excluded corridor")
        for raw in _list(summaries.get("reader_excluded"), "reader exclusions")
    }
    packets = [
        _mapping(raw, "corridor packet")
        for raw in _list(corridors.get("packets"), "corridor packets")
        if _mapping(raw, "corridor packet").get("corridor_id") not in excluded
    ]
    packet_order = {
        _text(packet.get("corridor_id"), "packet id"): index for index, packet in enumerate(packets)
    }
    accepted_names = _accepted_story_names(name_overrides)
    uncovered_names: dict[str, dict[str, object]] = {}

    def story_name(
        stable_id: str,
        kind: str,
        *,
        exact_title: str | None = None,
        owning_title: str | None = None,
        first_line: str | None = None,
        fallback: str = _UNNAMED_ROUTE,
        expression_or_label: str,
        label: str,
        flow_index: int,
        arm_id: str | None = None,
        control_id: str | None = None,
        packet_ids: Sequence[str] = (),
    ) -> tuple[str, str]:
        value, source = _resolve_story_name(
            stable_id=stable_id,
            overrides=accepted_names,
            exact_title=exact_title,
            owning_title=owning_title,
            first_line=first_line,
            fallback=fallback,
        )
        if source == "fallback":
            uncovered_names.setdefault(
                stable_id,
                {
                    "stable_id": stable_id,
                    "kind": kind,
                    "expression_or_label": expression_or_label,
                    "label": label,
                    "arm_id": arm_id,
                    "control_id": control_id,
                    "packet_ids": list(packet_ids),
                    "fallback": value,
                    "flow_index": flow_index,
                },
            )
        return value, source

    def owning_arm(node_id: str, label: str) -> str | None:
        candidates: list[tuple[int, str]] = []
        for region_id, arm_id in ownership.get(node_id, ()):
            region = regions.get(region_id)
            if region is None:
                continue
            split_id = region.get("split_node_id")
            if not isinstance(split_id, str) or split_id not in nodes:
                continue
            if split_id == node_id:
                continue
            split = nodes[split_id]
            if (
                split.get("kind") not in _CONTROL_KINDS
                or split.get("label") != label
                or split_id in secondary_controls
            ):
                continue
            candidates.append((region_depth[region_id], arm_id))
        return max(candidates)[1] if candidates else None

    packets_by_label: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    packets_by_arm: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    all_packets_by_label: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for packet in packets:
        label = _text(packet.get("owning_label"), "packet label")
        all_packets_by_label[label].append(packet)
        corridor = _mapping(packet.get("python_corridor"), "python corridor")
        story_ids = _list(corridor.get("narrative_statement_node_ids"), "story node ids")
        owner = owning_arm(_text(story_ids[0], "first story node"), label)
        (packets_by_arm[owner] if owner else packets_by_label[label]).append(packet)

    effects_by_label: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    effects_by_arm: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    secondary_by_label: dict[str, list[str]] = defaultdict(list)
    secondary_by_arm: dict[str, list[str]] = defaultdict(list)
    for mechanic in mechanics.values():
        if mechanic.get("kind") != "effect":
            continue
        node_id = _text(mechanic.get("node_id"), "effect node")
        label = _text(mechanic.get("label"), "effect label")
        owner = owning_arm(node_id, label)
        (effects_by_arm[owner] if owner else effects_by_label[label]).append(mechanic)

    controls_by_label: dict[str, list[str]] = defaultdict(list)
    children_by_arm: dict[str, list[str]] = defaultdict(list)
    for control_id, node in nodes.items():
        if node.get("reachable_from_entry") is not True or node.get("kind") not in _CONTROL_KINDS:
            continue
        label = _text(node.get("label"), "control label")
        owner = owning_arm(control_id, label)
        if control_id in secondary_controls:
            note = _secondary_control_note(control_id, nodes, regions_by_split, arms)
            (secondary_by_arm[owner] if owner else secondary_by_label[label]).append(note)
            continue
        if owner:
            children_by_arm[owner].append(control_id)
        else:
            controls_by_label[label].append(control_id)

    for control_ids in (*controls_by_label.values(), *children_by_arm.values()):
        control_ids.sort(key=lambda node_id: flow_order.get(node_id, 10**9))
    for owned_packets in (*packets_by_label.values(), *packets_by_arm.values()):
        owned_packets.sort(
            key=lambda packet: packet_order[_text(packet.get("corridor_id"), "packet")]
        )

    merge_titles: dict[str, str] = {}
    for packet in packets:
        result = results[_text(packet.get("corridor_id"), "packet id")]
        for raw in _list(packet.get("incoming_control_points"), "incoming controls"):
            control = _mapping(raw, "incoming control")
            if control.get("kind") == "merge":
                merge_titles.setdefault(
                    _text(control.get("node_id"), "merge id"),
                    _text(result.get("title"), "summary title"),
                )

    incoming_packet_titles: dict[str, list[str]] = defaultdict(list)
    outgoing_packet_titles: dict[str, list[str]] = defaultdict(list)
    for packet in packets:
        corridor_id = _text(packet.get("corridor_id"), "packet id")
        packet_title = _text(results[corridor_id].get("title"), "summary title")
        for raw in packet.get("next_control_points", []):
            control = _mapping(raw, "next control")
            control_id = control.get("node_id")
            if isinstance(control_id, str):
                incoming_packet_titles[control_id].append(packet_title)
        for raw in packet.get("incoming_control_points", []):
            control = _mapping(raw, "incoming control")
            control_id = control.get("node_id")
            if isinstance(control_id, str):
                outgoing_packet_titles[control_id].append(packet_title)

    visible_labels = set(packets_by_label)
    visible_labels.update(
        _text(nodes[node_id].get("label"), "control label")
        for node_ids in controls_by_label.values()
        for node_id in node_ids
    )
    visible_labels.update(
        _text(packet.get("owning_label"), "packet label")
        for values in packets_by_arm.values()
        for packet in values
    )
    label_order = sorted(
        visible_labels,
        key=lambda label: min(
            (
                flow_order[node_id]
                for node_id, node in nodes.items()
                if node.get("label") == label and node_id in flow_order
            ),
            default=10**9,
        ),
    )

    event_names: dict[str, str] = {}
    for label in label_order:
        assigned = packets_by_label.get(label, [])
        exact_title = _prose(assigned, results)[0] if assigned else None
        packet_ids = [
            _text(packet.get("corridor_id"), "event name corridor")
            for packet in all_packets_by_label.get(label, ())
        ]
        first_line = _first_readable_story_line(all_packets_by_label.get(label, ()))
        label_flow = min(
            (
                flow_order.get(node_id, 10**9)
                for node_id, node in nodes.items()
                if node.get("label") == label
            ),
            default=10**9,
        )
        event_name, _name_source = story_name(
            f"whole-game:label:{label}",
            "event",
            exact_title=exact_title,
            first_line=first_line,
            expression_or_label=label,
            label=label,
            flow_index=label_flow,
            packet_ids=packet_ids,
        )
        event_names[label] = event_name

    projected_controls: set[str] = set()
    projected_arms: dict[str, dict[str, object]] = {}
    arm_labels: dict[str, str] = {}
    condition_reads_by_arm: dict[str, list[Mapping[str, object]]] = {}
    destination_labels_by_arm: dict[str, str] = {}

    def project_choice(control_id: str, label: str, ancestors: frozenset[str]) -> dict[str, object]:
        if control_id in ancestors:
            raise ValueError(f"control nesting cycle at {control_id}")
        projected_controls.add(control_id)
        control = nodes[control_id]
        region = regions_by_split.get(control_id)
        if region is None:
            raise ValueError(f"control {control_id} has no M06 region")
        region_arms = [
            arms[_text(item, "region arm")] for item in _list(region.get("arm_ids"), "region arms")
        ]
        projected_arms = [
            project_arm(control, region, arm, label, ancestors | {control_id})
            for arm in sorted(
                region_arms,
                key=lambda item: _integer(item.get("ordinal"), "arm ordinal"),
            )
        ]
        exact_titles = _unique_text(incoming_packet_titles.get(control_id, ()))
        first_line = _first_readable_story_line(all_packets_by_label.get(label, ()))
        control_name, name_source = story_name(
            f"whole-game:control:{control_id}",
            "control",
            exact_title=exact_titles[0] if exact_titles else None,
            owning_title=event_names.get(label),
            first_line=first_line,
            expression_or_label=_text(control.get("source_text"), "control source").strip(),
            label=label,
            flow_index=flow_order.get(control_id, 10**9),
            control_id=control_id,
            packet_ids=[
                _text(packet.get("corridor_id"), "control context corridor")
                for packet in all_packets_by_label.get(label, ())
            ],
        )
        control_title = (
            control_name
            if name_source in {"accepted_override", "fallback"}
            else f"What follows {control_name}?"
        )
        if control.get("kind") == "if":
            for projected_arm in projected_arms:
                projected_arm["condition"] = control_title
        return {
            "key": f"story:{control_title}",
            "control_kind": "decision" if control.get("kind") == "menu" else "condition",
            "source": _reader_source(_flat_source(control)),
            "arms": projected_arms,
        }

    def project_arm(
        control: Mapping[str, object],
        region: Mapping[str, object],
        arm: Mapping[str, object],
        label: str,
        ancestors: frozenset[str],
    ) -> dict[str, object]:
        arm_id = _text(arm.get("id"), "arm id")
        entry_id = _text(arm.get("entry_node_id"), "arm entry")
        entry = nodes[entry_id]
        assigned = packets_by_arm.get(arm_id, [])
        children = [
            project_choice(child, label, ancestors)
            for child in children_by_arm.get(arm_id, ())
            if child not in ancestors
        ]
        destination = _destination_label(arm, label, nodes, flow_order)
        raw_merge_id = region.get("merge_node_id")
        merge_id = raw_merge_id if isinstance(raw_merge_id, str) else None
        arm_node_ids = {_text(item, "arm node") for item in _list(arm.get("node_ids"), "arm nodes")}
        unresolved = any(
            nodes[node_id].get("kind") == "unresolved"
            for node_id in arm_node_ids
            if node_id in nodes
        )
        terminal_ids = [
            _text(item, "terminal node")
            for item in _list(arm.get("terminal_node_ids"), "terminal nodes")
        ]
        if unresolved:
            outcome = "unresolved"
        elif children or destination:
            outcome = "continues"
        elif merge_id:
            outcome = "rejoins"
        elif terminal_ids:
            outcome = "ends"
        else:
            outcome = "continues"
        effect_text = [_effect_text(item) for item in effects_by_arm.get(arm_id, ())]
        destination_title = None
        destination_source = None
        destination_packet_ids: list[str] = []
        if destination:
            destination_packet_ids = [
                _text(packet.get("corridor_id"), "destination corridor")
                for packet in all_packets_by_label.get(destination, ())
            ]
            destination_exact = _first_packet_title(
                all_packets_by_label.get(destination, ()), results
            )
            destination_title, destination_source = story_name(
                f"whole-game:destination:{arm_id}",
                "destination",
                exact_title=destination_exact,
                owning_title=event_names.get(destination),
                first_line=_first_readable_story_line(
                    all_packets_by_label.get(destination, ())
                ),
                fallback=_UNRESOLVED_DESTINATION,
                expression_or_label=destination,
                label=destination,
                flow_index=min(
                    (
                        flow_order.get(node_id, 10**9)
                        for node_id, node in nodes.items()
                        if node.get("label") == destination
                    ),
                    default=flow_order.get(entry_id, 10**9),
                ),
                arm_id=arm_id,
                control_id=_text(control.get("id"), "control id"),
                packet_ids=destination_packet_ids,
            )
        rejoin_title = None
        rejoin_source = None
        if merge_id:
            merge_node = nodes.get(merge_id)
            merge_label = (
                _text(merge_node.get("label"), "merge label") if merge_node else label
            )
            rejoin_title, rejoin_source = story_name(
                f"whole-game:rejoin:{merge_id}",
                "rejoin",
                exact_title=merge_titles.get(merge_id),
                owning_title=event_names.get(merge_label),
                first_line=_first_readable_story_line(
                    all_packets_by_label.get(merge_label, ())
                ),
                expression_or_label=merge_id,
                label=merge_label,
                flow_index=flow_order.get(merge_id, flow_order.get(entry_id, 10**9)),
                arm_id=arm_id,
                control_id=_text(control.get("id"), "control id"),
                packet_ids=[
                    _text(packet.get("corridor_id"), "rejoin corridor")
                    for packet in all_packets_by_label.get(merge_label, ())
                ],
            )
        if assigned:
            assigned_title, outline, detail = _prose(assigned, results)
        else:
            assigned_title = None
            outline = _structure_arm_summary(
                destination_title=destination_title,
                rejoin_title=rejoin_title,
                outcome=outcome,
                nested_choices=children,
                location_title=event_names[label],
                effects=effect_text,
            )
            detail = outline
        if control.get("kind") == "menu":
            raw_caption, _condition = _arm_caption(control, entry)
            caption = raw_caption if _safe_story_name(raw_caption) else _UNNAMED_ROUTE
            if caption == _UNNAMED_ROUTE:
                caption, _caption_source = story_name(
                    f"whole-game:arm:{arm_id}",
                    "arm",
                    exact_title=assigned_title,
                    owning_title=event_names.get(label),
                    first_line=_first_readable_story_line(assigned),
                    expression_or_label=raw_caption,
                    label=label,
                    flow_index=flow_order.get(entry_id, 10**9),
                    arm_id=arm_id,
                    control_id=_text(control.get("id"), "control id"),
                    packet_ids=[
                        _text(packet.get("corridor_id"), "arm corridor")
                        for packet in assigned
                    ],
                )
            condition = None
        else:
            entry_metadata = _mapping(entry.get("metadata", {}), "arm entry metadata")
            raw_condition = entry_metadata.get("condition")
            raw_arm = (
                raw_condition
                if isinstance(raw_condition, str) and raw_condition
                else _text(entry.get("source_text"), "condition arm source").strip()
            )
            exact_arm_title = assigned_title
            if exact_arm_title is None and destination_source != "fallback":
                exact_arm_title = destination_title
            if exact_arm_title is None and rejoin_source != "fallback":
                exact_arm_title = rejoin_title
            caption, _caption_source = story_name(
                f"whole-game:arm:{arm_id}",
                "arm",
                exact_title=exact_arm_title,
                owning_title=event_names.get(label),
                first_line=_first_readable_story_line(
                    assigned or all_packets_by_label.get(destination or label, ())
                ),
                expression_or_label=raw_arm,
                label=label,
                flow_index=flow_order.get(entry_id, 10**9),
                arm_id=arm_id,
                control_id=_text(control.get("id"), "control id"),
                packet_ids=[
                    _text(packet.get("corridor_id"), "arm corridor")
                    for packet in assigned
                ],
            )
            condition = None
        reads = [
            _mapping(item, "state read") for item in _list(arm.get("state_reads"), "state reads")
        ]
        if control.get("kind") == "if":
            direct_reads = [
                item
                for item in reads
                if not isinstance(item.get("node_id"), str)
                or item.get("node_id") in {control.get("id"), entry_id}
            ]
            condition_reads_by_arm[arm_id] = direct_reads
        if destination:
            destination_labels_by_arm[arm_id] = destination
        warnings = []
        if unresolved:
            warnings.append("Python marked unresolved behavior on this route.")
        if control.get("kind") == "if":
            warnings.append(
                f"Python condition: {_text(control.get('source_text'), 'condition source').strip()}"
            )
        warnings.extend(
            f"Python control: {note}" for note in secondary_by_arm.get(arm_id, ())
        )
        source = _flat_source(entry)
        selection_id = f"whole-game:arm:{arm_id}"
        rejoin_binding = None
        if merge_id:
            rejoin_source = (
                _flat_source(nodes[merge_id]) if merge_id in nodes else _flat_source(control)
            )
            source_identity = _reader_source(rejoin_source)
            continuation_identity = (
                f"{merge_id}\0{source_identity['relative_path']}\0"
                f"{source_identity['start_line']}\0{source_identity['end_line']}"
            )
            rejoin_selection = (
                "story-map-v2-continuation:"
                + hashlib.sha256(continuation_identity.encode("utf-8")).hexdigest()
            )
            rejoin_binding = _binding(
                rejoin_selection,
                "generic_scene",
                merge_id,
                "story_map_v2_continuation",
                rejoin_source,
            )
        projected = {
            "selection_id": selection_id,
            "caption": caption,
            "outcome_kind": outcome,
            "outcome_summary": outline,
            "outline_summary": outline,
            "detail_summary": detail,
            "condition": condition,
            "effects": effect_text,
            "destination_id": f"story:{destination_title or caption}",
            "rejoin_node_id": f"story:{rejoin_title}" if rejoin_title else None,
            "rejoin_line": (
                _flat_source(nodes[merge_id])["start_line"]
                if merge_id and merge_id in nodes
                else None
            ),
            "reachability": "unresolved" if unresolved else "reachable",
            "warnings": warnings,
            "binding": _binding(
                selection_id,
                "generic_scene",
                f"story:{destination_title}" if destination_title else entry_id,
                "story_map_v2_arm",
                source,
            ),
            "rejoin_binding": rejoin_binding,
            "nested_choices": children,
            "route_flow": [],
        }
        projected_arms[arm_id] = projected
        arm_labels[arm_id] = label
        return projected

    event_prototypes: dict[str, dict[str, object]] = {}
    included_corridors: list[str] = []
    for label in label_order:
        assigned = packets_by_label.get(label, [])
        choices = [
            project_choice(control_id, label, frozenset())
            for control_id in controls_by_label.get(label, ())
        ]
        if assigned:
            _title, outline, detail = _prose(assigned, results)
        else:
            outline = ""
            detail = ""
        title = event_names[label]
        source = _label_source(label, nodes, flow_order)
        selection_id = f"whole-game:label:{label}"
        label_effects = [_effect_text(item) for item in effects_by_label.get(label, ())]
        secondary_notes = secondary_by_label.get(label, ())
        included_corridors.extend(
            _text(packet.get("corridor_id"), "event corridor") for packet in assigned
        )
        event_prototypes[label] = {
            "selection_id": selection_id,
            "title": title,
            "summary": outline,
            "outline_summary": outline,
            "detail_summary": detail,
            "characters": [],
            "reachability": "reachable",
            "warnings": [
                f"Python label: {label}",
                *(f"Python state change: {effect}" for effect in label_effects),
                *(f"Python control: {note}" for note in secondary_notes),
            ],
            "binding": _binding(
                selection_id,
                "generic_scene",
                f"story:{title}",
                "story_map_v2_event",
                source,
            ),
            "choices": choices,
        }

    for arm_id, destination_label in destination_labels_by_arm.items():
        destination_event = event_prototypes.get(destination_label)
        if destination_event is not None:
            projected_arms[arm_id]["destination_target_selection_id"] = destination_event[
                "selection_id"
            ]
    for projected_arm in projected_arms.values():
        rejoin_binding = projected_arm.get("rejoin_binding")
        if isinstance(rejoin_binding, dict):
            projected_arm["rejoin_target_selection_id"] = rejoin_binding["selection_id"]

    assignment_facts = [
        mechanic
        for mechanic in mechanics.values()
        if mechanic.get("kind") == "effect" and isinstance(mechanic.get("state_effect"), dict)
    ]
    assignments_by_variable: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for mechanic in assignment_facts:
        effect = _mapping(mechanic.get("state_effect"), "assignment state effect")
        assignments_by_variable[_text(effect.get("variable"), "assignment variable")].append(
            mechanic
        )
    graph_outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        graph_outgoing[_text(edge.get("source"), "provenance edge source")].append(
            _text(edge.get("target"), "provenance edge target")
        )
    relevant_read_nodes = {
        _text(read.get("node_id"), "provenance read node")
        for reads in condition_reads_by_arm.values()
        for read in reads
        if isinstance(read.get("node_id"), str)
    }
    relevant_read_nodes.update(
        _text(arms[arm_id].get("entry_node_id"), "provenance fallback read node")
        for arm_id, reads in condition_reads_by_arm.items()
        if reads and any(not isinstance(read.get("node_id"), str) for read in reads)
    )
    reachable_read_nodes: dict[str, set[str]] = {}

    def assignment_target(node_id: str) -> tuple[str, str] | None:
        node = nodes.get(node_id)
        if node is None:
            return None
        label = _text(node.get("label"), "assignment label")
        owner = owning_arm(node_id, label)
        if owner is not None and owner in projected_arms:
            projected_arm = projected_arms[owner]
            return (
                _text(projected_arm.get("selection_id"), "assignment arm selection"),
                _text(projected_arm.get("caption"), "assignment arm title"),
            )
        event = event_prototypes.get(label)
        if event is None:
            return None
        return (
            _text(event.get("selection_id"), "assignment event selection"),
            _text(event.get("title"), "assignment event title"),
        )

    for arm_id, reads in condition_reads_by_arm.items():
        if not reads:
            continue
        entry_id = _text(arms[arm_id].get("entry_node_id"), "provenance arm entry")
        reads_by_variable: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        for read in reads:
            reads_by_variable[_text(read.get("variable"), "state read variable")].append(read)
        provenance: list[dict[str, object]] = []
        for variable, variable_reads in sorted(reads_by_variable.items()):
            read_node_ids = {
                _text(read.get("node_id"), "state read node")
                for read in variable_reads
                if isinstance(read.get("node_id"), str)
            }
            if not read_node_ids:
                read_node_ids = {entry_id}
            candidates: list[tuple[int, str, Mapping[str, object], str, str]] = []
            for mechanic in assignments_by_variable.get(variable, ()):
                node_id = _text(mechanic.get("node_id"), "assignment node")
                node_flow = flow_order.get(node_id)
                if node_flow is None:
                    continue
                if node_id not in reachable_read_nodes:
                    reachable_read_nodes[node_id] = _reachable_targets(
                        node_id, relevant_read_nodes, graph_outgoing
                    )
                compatible_reads = [
                    read
                    for read in variable_reads
                    if (
                        read.get("node_id") in reachable_read_nodes[node_id]
                        and node_flow < flow_order.get(cast(str, read.get("node_id")), -1)
                    )
                ]
                if not compatible_reads and entry_id in reachable_read_nodes[node_id]:
                    entry_flow = flow_order.get(entry_id)
                    if entry_flow is not None and node_flow < entry_flow:
                        compatible_reads = variable_reads
                if not compatible_reads:
                    continue
                effect = _mapping(mechanic.get("state_effect"), "assignment state effect")
                if not any(
                    _state_write_may_set_read(
                        _text(read.get("expression"), "state read expression"),
                        variable,
                        _text(effect.get("operator"), "assignment operator"),
                        _text(effect.get("expression"), "assignment expression"),
                    )
                    for read in compatible_reads
                ):
                    continue
                target = assignment_target(node_id)
                if target is None:
                    continue
                target_selection_id, target_title = target
                candidates.append((node_flow, node_id, mechanic, target_selection_id, target_title))
            candidates.sort(key=lambda item: (item[0], item[1]))
            relationship = "exact" if len(candidates) == 1 else "possible"
            for _node_flow, node_id, _mechanic, target_selection_id, target_title in candidates:
                provenance.append(
                    {
                        "variable": variable,
                        "relationship_strength": relationship,
                        "target_selection_id": target_selection_id,
                        "target_title": target_title,
                        "source": _reader_source(_flat_source(nodes[node_id])),
                    }
                )
            if not candidates:
                evidence_node = next(
                    (nodes[node_id] for node_id in read_node_ids if node_id in nodes),
                    nodes[entry_id],
                )
                provenance.append(
                    {
                        "variable": variable,
                        "relationship_strength": "unresolved",
                        "target_selection_id": None,
                        "target_title": None,
                        "source": _reader_source(_flat_source(evidence_node)),
                    }
                )
        if provenance:
            projected_arms[arm_id]["state_provenance"] = provenance

    route_plan = _label_route_plan(
        graph=graph,
        skeleton=skeleton,
        nodes=nodes,
        edges=edges,
        visible_labels=set(event_prototypes),
        arm_labels=arm_labels,
        interleaved_arms=set(children_by_arm),
        owning_arm=owning_arm,
    )
    owned_labels: set[str] = set()
    placements = cast(dict[str, dict[str, object]], route_plan["placements"])
    for label in label_order:
        placement = placements.get(label)
        if not isinstance(placement, dict):
            continue
        arm_id = placement.get("arm_id")
        if not isinstance(arm_id, str):
            continue
        projected_arm = projected_arms.get(arm_id)
        if projected_arm is None:
            raise ValueError(f"route-flow owner {arm_id} is not reader-visible")
        route_flow = cast(list[dict[str, object]], projected_arm["route_flow"])
        route_flow.append(
            {
                "kind": "event",
                "transfer_kind": placement["transfer_kind"],
                "entry_kind": "unique",
                "event": event_prototypes[label],
            }
        )
        owned_labels.add(label)

    for raw_reference in cast(list[dict[str, object]], route_plan["references"]):
        arm_id = _text(raw_reference.get("arm_id"), "route reference arm")
        label = _text(raw_reference.get("target_label"), "route reference label")
        projected_arm = projected_arms.get(arm_id)
        event = event_prototypes.get(label)
        if projected_arm is None or event is None:
            continue
        cast(list[dict[str, object]], projected_arm["route_flow"]).append(
            {
                "kind": "reference",
                "transfer_kind": raw_reference["transfer_kind"],
                "entry_kind": raw_reference["entry_kind"],
                "target_selection_id": event["selection_id"],
                "title": event["title"],
            }
        )

    for projected_arm in projected_arms.values():
        cast(list[dict[str, object]], projected_arm["route_flow"]).sort(
            key=lambda item: label_order.index(
                _route_item_label(item, event_prototypes)
            )
        )
    events = [event_prototypes[label] for label in label_order if label not in owned_labels]

    for arm_id, assigned in packets_by_arm.items():
        del arm_id
        included_corridors.extend(
            _text(packet.get("corridor_id"), "arm corridor") for packet in assigned
        )
    expected_corridors = {_text(packet.get("corridor_id"), "reader corridor") for packet in packets}
    if len(included_corridors) != len(set(included_corridors)):
        raise ValueError("a reader corridor was attached more than once")
    if set(included_corridors) != expected_corridors:
        raise ValueError("reader corridor attachment is incomplete")
    expected_controls = {
        node_id
        for node_id, node in nodes.items()
        if node.get("reachable_from_entry") is True and node.get("kind") in _CONTROL_KINDS
    }
    expected_visible_controls = expected_controls.difference(secondary_controls)
    if projected_controls != expected_visible_controls:
        missing = sorted(expected_visible_controls.difference(projected_controls))
        raise ValueError(f"reader control projection is incomplete: {missing[:8]}")

    packet_by_id = {
        _text(packet.get("corridor_id"), "inventory packet id"): packet for packet in packets
    }
    incoming_labels: dict[str, list[str]] = defaultdict(list)
    outgoing_labels: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source = nodes.get(_text(edge.get("source"), "inventory edge source"))
        target = nodes.get(_text(edge.get("target"), "inventory edge target"))
        if source is None or target is None:
            continue
        source_label = source.get("label")
        target_label = target.get("label")
        if (
            isinstance(source_label, str)
            and isinstance(target_label, str)
            and source_label != target_label
        ):
            outgoing_labels[source_label].append(target_label)
            incoming_labels[target_label].append(source_label)

    def inventory_assignment_sites(item: Mapping[str, object]) -> list[dict[str, object]]:
        item_arm = item.get("arm_id")
        item_control = item.get("control_id")
        candidate_arms: Sequence[Mapping[str, object]]
        if isinstance(item_arm, str) and item_arm in arms:
            candidate_arms = [arms[item_arm]]
        elif isinstance(item_control, str) and item_control in regions_by_split:
            region = regions_by_split[item_control]
            candidate_arms = [
                arms[_text(raw_arm_id, "inventory region arm")]
                for raw_arm_id in _list(region.get("arm_ids"), "inventory region arms")
            ]
        else:
            candidate_arms = list(arms.values())
        sites: list[dict[str, object]] = []
        seen_sites: set[tuple[str, str]] = set()
        for candidate_arm in candidate_arms:
            for raw_write in _list(candidate_arm.get("state_writes"), "inventory state writes"):
                write = _mapping(raw_write, "inventory state write")
                node_id = _text(write.get("node_id"), "inventory assignment node")
                node = nodes.get(node_id)
                if node is None or (
                    not isinstance(item_arm, str)
                    and not isinstance(item_control, str)
                    and node.get("label") != item.get("label")
                ):
                    continue
                expression = _text(write.get("expression"), "inventory assignment expression")
                key = (node_id, expression)
                if key in seen_sites:
                    continue
                seen_sites.add(key)
                sites.append(
                    {
                        "variable": _text(write.get("variable"), "inventory assignment variable"),
                        "expression": expression,
                        "source": _reader_source(_flat_source(node)),
                    }
                )
        return sites

    def inventory_context(item: Mapping[str, object]) -> list[dict[str, object]]:
        packet_ids = [
            raw_id for raw_id in item.get("packet_ids", []) if isinstance(raw_id, str)
        ]
        if not packet_ids:
            packet_ids = [
                _text(packet.get("corridor_id"), "inventory context corridor")
                for packet in all_packets_by_label.get(
                    _text(item.get("label"), "inventory context label"), ()
                )
            ]
        context: list[dict[str, object]] = []
        for corridor_id in packet_ids:
            packet = packet_by_id.get(corridor_id)
            result = results.get(corridor_id)
            if packet is None or result is None:
                continue
            story_line = _first_readable_story_line([packet])
            context.append(
                {
                    "corridor_id": corridor_id,
                    "title": _text(result.get("title"), "inventory context title"),
                    "story_excerpt": story_line or "",
                }
            )
            if len(context) == 3:
                break
        return context

    kind_order = {"event": 0, "control": 1, "arm": 2, "destination": 3, "rejoin": 4}
    sorted_uncovered = sorted(
        uncovered_names.values(),
        key=lambda item: (
            _integer(item.get("flow_index"), "inventory flow index"),
            kind_order[_text(item.get("kind"), "inventory kind")],
            _text(item.get("stable_id"), "inventory stable id"),
        ),
    )
    inventory_items: list[dict[str, object]] = []
    for item in sorted_uncovered:
        label = _text(item.get("label"), "inventory label")
        control_id = item.get("control_id")
        arm_id = item.get("arm_id")
        incoming_titles = [
            event_names[value] for value in incoming_labels.get(label, ()) if value in event_names
        ]
        outgoing_titles = [
            event_names[value] for value in outgoing_labels.get(label, ()) if value in event_names
        ]
        if isinstance(control_id, str):
            incoming_titles.extend(incoming_packet_titles.get(control_id, ()))
            outgoing_titles.extend(outgoing_packet_titles.get(control_id, ()))
        if isinstance(arm_id, str):
            incoming_titles.append(event_names.get(arm_labels.get(arm_id, label), _UNNAMED_ROUTE))
            for packet in packets_by_arm.get(arm_id, ()):
                corridor_id = _text(packet.get("corridor_id"), "inventory arm corridor")
                outgoing_titles.append(_text(results[corridor_id].get("title"), "arm title"))
        nearby_context = inventory_context(item)
        if not nearby_context:
            nearby_context = [
                {"corridor_id": None, "title": title, "story_excerpt": ""}
                for title in _unique_text(incoming_titles + outgoing_titles)
                if _safe_story_name(title)
            ][:3]
        if not nearby_context:
            nearby_context = [
                {
                    "corridor_id": None,
                    "title": "No readable nearby story context",
                    "story_excerpt": "",
                    "unresolved_reason": (
                        "Python reaches this structural destination without a reader-visible "
                        "corridor on either side."
                    ),
                }
            ]
        inventory_items.append(
            {
                "stable_id": _text(item.get("stable_id"), "inventory stable id"),
                "kind": _text(item.get("kind"), "inventory kind"),
                "fallback": _text(item.get("fallback"), "inventory fallback"),
                "expression_or_label": _text(
                    item.get("expression_or_label"), "inventory expression or label"
                ),
                "assignment_sites": inventory_assignment_sites(item),
                "nearby_story_context": nearby_context,
                "incoming_story_titles": _unique_text(
                    [title for title in incoming_titles if _safe_story_name(title)]
                )[:4],
                "outgoing_story_titles": _unique_text(
                    [title for title in outgoing_titles if _safe_story_name(title)]
                )[:4],
                "resolution_attempts": {
                    "accepted_override": accepted_names.get(
                        _text(item.get("stable_id"), "inventory override id")
                    ),
                    "exact_corridor_titles": [
                        _text(context.get("title"), "inventory attempted title")
                        for context in nearby_context
                        if isinstance(context.get("corridor_id"), str)
                    ],
                    "owning_event_title": event_names.get(label),
                    "first_readable_narrative": next(
                        (
                            _text(context.get("story_excerpt"), "inventory story excerpt")
                            for context in nearby_context
                            if context.get("story_excerpt")
                        ),
                        None,
                    ),
                },
            }
        )
    if name_inventory is not None:
        name_inventory[:] = inventory_items

    low_ids = {
        corridor_id
        for corridor_id, result in results.items()
        if result.get("packet_shape_grade") == "LOW" and corridor_id not in excluded
    }
    counts = _mapping(corridors.get("counts"), "corridor counts")
    page: dict[str, object] = {
        "schema": "story-map-v2-page-v1",
        "status": "synthesized",
        "reason": None,
        "title": "Ms. Denvers — Whole Story",
        "overview": (
            "Follow Wanda's story from the opening through every Python-owned decision, "
            "condition, route continuation, rejoin, loop, unresolved mechanic, and ending."
        ),
        "analysis_notes": [
            WHOLE_GAME_READER_MARKER,
            (
                f"{len(expected_corridors)} corridor summaries are attached under "
                f"{len(event_prototypes)} Python label continuations and their owning route arms."
            ),
            _route_plan_note(route_plan),
            (
                f"{len(low_ids)} exact LOW fragments remain in their owning detail flows; "
                f"{len(excluded)} packet-shape FAIL technical messages are omitted from the reader."
            ),
            (
                f"Coverage retained: {counts.get('included_narrative_statements')} narrative "
                f"statements, {counts.get('mechanics')} control/effect facts, and "
                f"{counts.get('state_effects')} direct state effects."
            ),
        ],
        "sections": [
            {
                "id": "phase05-whole-game-reader",
                "title": "Ms. Denvers — Whole Story",
                "summary": "The complete story in Python execution order.",
                "events": events,
            }
        ],
    }
    return page


def _label_route_plan(
    *,
    graph: Mapping[str, object],
    skeleton: Mapping[str, object],
    nodes: Mapping[str, Mapping[str, object]],
    edges: Sequence[Mapping[str, object]],
    visible_labels: set[str],
    arm_labels: Mapping[str, str],
    interleaved_arms: set[str],
    owning_arm: Callable[[str, str], str | None],
) -> dict[str, object]:
    """Classify cross-label entries without turning uncertain ownership into nesting."""

    skeleton_story = _mapping(skeleton.get("skeleton"), "whole-game skeleton story")
    declared_transitions = {
        (
            _text(item.get("source_label"), "transition source label"),
            _text(item.get("target_label"), "transition target label"),
            _text(item.get("transfer_kind"), "transition kind"),
        )
        for raw in _list(skeleton_story.get("label_transitions"), "label transitions")
        for item in (_mapping(raw, "label transition"),)
    }
    transfers: list[dict[str, str]] = []
    for edge in edges:
        source_id = _text(edge.get("source"), "route transfer source")
        target_id = _text(edge.get("target"), "route transfer target")
        source = nodes.get(source_id)
        target = nodes.get(target_id)
        if source is None or target is None:
            continue
        if (
            source.get("reachable_from_entry") is not True
            or target.get("reachable_from_entry") is not True
        ):
            continue
        source_label = source.get("label")
        target_label = target.get("label")
        if (
            not isinstance(source_label, str)
            or not isinstance(target_label, str)
            or source_label == target_label
        ):
            continue
        raw_kind = _text(edge.get("kind"), "route transfer kind")
        if (source_label, target_label, raw_kind) not in declared_transitions:
            raise ValueError(
                "graph cross-label edge is missing from skeleton label_transitions: "
                f"{source_label} -> {target_label} ({raw_kind})"
            )
        transfers.append(
            {
                "source_id": source_id,
                "source_label": source_label,
                "target_label": target_label,
                "transfer_kind": _route_transfer_kind(raw_kind),
            }
        )

    loop_labels = {
        _text(raw_label, "loop label")
        for raw_loop in _list(skeleton_story.get("loops"), "skeleton loops")
        for loop in (_mapping(raw_loop, "skeleton loop"),)
        for raw_label in _list(loop.get("labels"), "skeleton loop labels")
    }
    incoming: dict[str, list[dict[str, str]]] = defaultdict(list)
    all_labels = {
        _text(node.get("label"), "graph node label")
        for node in nodes.values()
        if isinstance(node.get("label"), str)
    }
    for transfer in transfers:
        if transfer["transfer_kind"] != "return":
            incoming[transfer["target_label"]].append(transfer)

    entry_label = _text(graph.get("entry_label"), "route graph entry label")
    owner_by_label: dict[str, str | None] = {
        label: None
        for label in all_labels
        if label == entry_label or label in loop_labels or not incoming.get(label)
    }
    entry_kinds: dict[str, str] = {
        label: ("loop" if label in loop_labels else "direct") for label in owner_by_label
    }
    transfer_kinds_by_label: dict[str, str] = {}

    pending = set(all_labels).difference(owner_by_label)
    while pending:
        progressed = False
        for label in sorted(pending):
            label_transfers = incoming.get(label, [])
            candidates: list[str | None] = []
            unresolved_source = False
            for transfer in label_transfers:
                local_owner = owning_arm(transfer["source_id"], transfer["source_label"])
                if local_owner is not None:
                    candidates.append(local_owner)
                elif transfer["source_label"] in owner_by_label:
                    candidates.append(owner_by_label[transfer["source_label"]])
                else:
                    unresolved_source = True
                    break
            if unresolved_source:
                continue
            kinds = {transfer["transfer_kind"] for transfer in label_transfers}
            transfer_kinds_by_label[label] = next(iter(kinds)) if len(kinds) == 1 else "unresolved"
            distinct = set(candidates)
            if len(distinct) == 1:
                owner = next(iter(distinct))
                owner_by_label[label] = owner
                entry_kinds[label] = "unique" if owner is not None else "direct"
            else:
                owner_by_label[label] = None
                entry_kinds[label] = "shared"
            pending.remove(label)
            progressed = True
        if not progressed:
            break

    for label in pending:
        owner_by_label[label] = None
        entry_kinds[label] = "unresolved"
        transfer_kinds_by_label[label] = "unresolved"

    placements: dict[str, dict[str, object]] = {
        label: {
            "arm_id": owner,
            "transfer_kind": transfer_kinds_by_label.get(label, "unresolved"),
        }
        for label, owner in owner_by_label.items()
        if label in visible_labels and owner is not None and entry_kinds.get(label) == "unique"
    }
    cyclic_placements = _placement_cycle_labels(placements, arm_labels)
    interleaved_labels = {
        label
        for label, placement in placements.items()
        if placement.get("arm_id") in interleaved_arms
    }
    for label in cyclic_placements | interleaved_labels:
        placements.pop(label, None)
        owner_by_label[label] = None
        entry_kinds[label] = "unresolved"

    references: list[dict[str, object]] = []
    seen_references: set[tuple[str, str, str]] = set()
    for label in sorted(visible_labels):
        entry_kind = entry_kinds.get(label)
        if entry_kind not in {"loop", "unresolved"}:
            continue
        for transfer in incoming.get(label, ()):
            if entry_kind == "loop" and transfer["source_label"] in loop_labels:
                continue
            owner = owning_arm(transfer["source_id"], transfer["source_label"])
            if owner is None:
                owner = owner_by_label.get(transfer["source_label"])
            if owner is None:
                continue
            key = (owner, label, entry_kind)
            if key in seen_references:
                continue
            seen_references.add(key)
            references.append(
                {
                    "arm_id": owner,
                    "target_label": label,
                    "transfer_kind": transfer["transfer_kind"],
                    "entry_kind": entry_kind,
                }
            )

    transfer_counts = Counter(transfer["transfer_kind"] for transfer in transfers)
    entry_counts = Counter(entry_kinds.get(label, "unresolved") for label in visible_labels)
    return {
        "placements": placements,
        "references": references,
        "counts": {
            "jump": transfer_counts["jump"],
            "fallthrough": transfer_counts["fallthrough"],
            "call": transfer_counts["call"],
            "return": transfer_counts["return"],
            "unique": entry_counts["unique"],
            "shared": entry_counts["shared"],
            "loop": entry_counts["loop"],
            "unresolved": entry_counts["unresolved"],
            "references": len(references),
        },
    }


def _route_transfer_kind(value: str) -> str:
    if value == "choice_body":
        return "fallthrough"
    if value in {"jump", "fallthrough", "call", "return"}:
        return value
    return "unresolved"


def _placement_cycle_labels(
    placements: Mapping[str, Mapping[str, object]], arm_labels: Mapping[str, str]
) -> set[str]:
    cycles: set[str] = set()
    for start in placements:
        order: list[str] = []
        positions: dict[str, int] = {}
        label = start
        while label in placements:
            if label in positions:
                cycles.update(order[positions[label] :])
                break
            positions[label] = len(order)
            order.append(label)
            arm_id = placements[label].get("arm_id")
            if not isinstance(arm_id, str) or arm_id not in arm_labels:
                break
            label = arm_labels[arm_id]
    return cycles


def _route_item_label(
    item: Mapping[str, object], events: Mapping[str, Mapping[str, object]]
) -> str:
    if item.get("kind") == "event":
        event = _mapping(item.get("event"), "route-flow event")
        selection_id = _text(event.get("selection_id"), "route-flow event selection")
    else:
        selection_id = _text(
            item.get("target_selection_id"), "route-flow reference selection"
        )
    for label, event in events.items():
        if event.get("selection_id") == selection_id:
            return label
    raise ValueError(f"route-flow target {selection_id} has no event prototype")


def _route_plan_note(route_plan: Mapping[str, object]) -> str:
    counts = _mapping(route_plan.get("counts"), "route-plan counts")
    return (
        "Cross-label flow classified: "
        f"{counts.get('jump')} jumps, {counts.get('fallthrough')} fallthroughs, "
        f"{counts.get('call')} calls, and {counts.get('return')} returns; "
        f"{counts.get('unique')} unique entries, {counts.get('shared')} shared entries, "
        f"{counts.get('loop')} loop/revisit entries, {counts.get('references')} references, "
        f"and {counts.get('unresolved')} unresolved owners."
    )


def _validate_inputs(
    graph: Mapping[str, object],
    skeleton: Mapping[str, object],
    corridors: Mapping[str, object],
    summaries: Mapping[str, object],
) -> None:
    entry = _text(graph.get("entry_label"), "graph entry label")
    if skeleton.get("entry_label") != entry or corridors.get("entry_label") != entry:
        raise ValueError("whole-game artifacts disagree on the entry label")
    if skeleton.get("parser_extraction_grade") != "PASS":
        raise ValueError("parser extraction is not PASS")
    if skeleton.get("story_coverage_grade") != "PASS" or corridors.get("coverage_grade") != "PASS":
        raise ValueError("whole-game story coverage is not PASS")
    packets = _list(corridors.get("packets"), "corridor packets")
    results = _list(summaries.get("results"), "summary results")
    if len(packets) != 597 or len(results) != len(packets):
        raise ValueError("expected the complete 597-corridor summary set")
    if any(_mapping(item, "summary result").get("fidelity_grade") != "PASS" for item in results):
        raise ValueError("every AI corridor summary must pass fidelity review")
    excluded = _list(summaries.get("reader_excluded"), "reader exclusions")
    if len(excluded) != 3:
        raise ValueError("exactly three technical FAIL packets must be reader-excluded")


def _prose(
    packets: Sequence[Mapping[str, object]],
    results: Mapping[str, Mapping[str, object]],
) -> tuple[str, str, str]:
    if not packets:
        raise ValueError("reader prose requires an assigned corridor")
    values = [results[_text(packet.get("corridor_id"), "prose corridor")] for packet in packets]
    preferred = next(
        (item for item in values if item.get("packet_shape_grade") != "LOW"), values[0]
    )
    raw_title = _text(preferred.get("title"), "prose title")
    title = (
        raw_title
        if _safe_story_name(raw_title)
        else _first_readable_story_line(packets) or _UNNAMED_ROUTE
    )
    outline = _visible_story_prose(
        _text(preferred.get("summary"), "prose summary"), fallback=title
    )
    detail_parts: list[str] = []
    for item in values:
        raw_item_title = _text(item.get("title"), "detail title")
        item_title = raw_item_title if _safe_story_name(raw_item_title) else title
        item_detail = _visible_story_prose(
            _text(item.get("detail"), "detail prose"), fallback=outline
        )
        detail_parts.append(f"{item_title}\n{item_detail}")
        for raw_child in _list(item.get("presentation_children"), "presentation children"):
            child = _mapping(raw_child, "presentation child")
            raw_child_title = _text(child.get("title"), "child title")
            child_title = raw_child_title if _safe_story_name(raw_child_title) else title
            child_summary = _visible_story_prose(
                _text(child.get("summary"), "child summary"), fallback=outline
            )
            detail_parts.append(
                f"{child_title} — "
                f"{child_summary}"
            )
    return title, outline, "\n\n".join(detail_parts)


def _projected_control_title(choice: Mapping[str, object]) -> str:
    key = _text(choice.get("key"), "projected control key")
    return key.removeprefix("story:").strip()


def _structure_arm_summary(
    *,
    destination_title: str | None,
    rejoin_title: str | None,
    outcome: str,
    nested_choices: Sequence[Mapping[str, object]],
    location_title: str,
    effects: Sequence[str],
) -> str:
    if destination_title:
        return f"Continues to {destination_title}."
    if nested_choices:
        titles = [_projected_control_title(choice) for choice in nested_choices]
        return f"Next: {'; '.join(titles)}."
    if rejoin_title:
        return f"Rejoins at {rejoin_title}."
    if outcome == "ends":
        return f"Ends during {location_title}."
    if outcome == "unresolved":
        return f"Unresolved during {location_title}."
    if effects:
        return f"State change: {'; '.join(effects)}."
    return ""


def _secondary_control(
    control_id: str,
    nodes: Mapping[str, Mapping[str, object]],
    regions_by_split: Mapping[str, Mapping[str, object]],
    arms: Mapping[str, Mapping[str, object]],
) -> bool:
    control = nodes[control_id]
    source_text = _text(control.get("source_text"), "control source").casefold()
    if "persistent.show_hints" in source_text or "config.developer" in source_text:
        return True
    source = _flat_source(control)
    path = _text(source.get("path"), "control path").replace("\\", "/").casefold()
    line = _integer(source.get("start_line"), "control line")
    if control.get("label") == "start" and path.endswith("/v0.01_clean.rpy") and line <= 24:
        return True
    region = regions_by_split[control_id]
    captions = []
    for raw_arm_id in _list(region.get("arm_ids"), "secondary control arms"):
        arm = arms[_text(raw_arm_id, "secondary arm")]
        entry = nodes[_text(arm.get("entry_node_id"), "secondary arm entry")]
        captions.append(_arm_caption(control, entry)[0].casefold())
    return bool(captions) and set(captions) <= {"clean", "ces.wint"}


def _secondary_control_note(
    control_id: str,
    nodes: Mapping[str, Mapping[str, object]],
    regions_by_split: Mapping[str, Mapping[str, object]],
    arms: Mapping[str, Mapping[str, object]],
) -> str:
    control = nodes[control_id]
    source = _flat_source(control)
    region = regions_by_split[control_id]
    region_arms = sorted(
        (
            arms[_text(raw_arm_id, "secondary arm")]
            for raw_arm_id in _list(region.get("arm_ids"), "secondary control arms")
        ),
        key=lambda item: _integer(item.get("ordinal"), "secondary arm ordinal"),
    )
    captions = [
        _arm_caption(
            control,
            nodes[_text(arm.get("entry_node_id"), "secondary arm entry")],
        )[0]
        for arm in region_arms
    ]
    return (
        f"{_text(source.get('path'), 'control path')}:"
        f"{_integer(source.get('start_line'), 'control line')} — "
        f"{_text(control.get('source_text'), 'control source').strip()} "
        f"Routes: {' / '.join(captions)}"
    )


def _arm_caption(
    control: Mapping[str, object], entry: Mapping[str, object]
) -> tuple[str, str | None]:
    metadata = _mapping(entry.get("metadata", {}), "arm entry metadata")
    if control.get("kind") == "menu":
        caption = metadata.get("caption")
        return (
            _text(caption, "menu caption").strip()
            if isinstance(caption, str) and caption.strip()
            else "Continue",
            None,
        )
    if entry.get("kind") == "merge":
        return "Otherwise", None
    condition = metadata.get("condition")
    raw = _text(entry.get("source_text"), "condition arm source").strip().rstrip(":")
    if isinstance(condition, str) and condition:
        return f"Requires: {condition}", condition
    return ("Otherwise" if raw == "else" else raw, None)


def _destination_label(
    arm: Mapping[str, object],
    owner_label: str,
    nodes: Mapping[str, Mapping[str, object]],
    flow_order: Mapping[str, int],
) -> str | None:
    candidates = {
        _text(nodes[node_id].get("label"), "destination label")
        for raw in _list(arm.get("node_ids"), "arm nodes")
        for node_id in (_text(raw, "arm node"),)
        if node_id in nodes and nodes[node_id].get("label") != owner_label
    }
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda label: min(
            (
                flow_order.get(node_id, 10**9)
                for node_id, node in nodes.items()
                if node.get("label") == label
            ),
            default=10**9,
        ),
    )


def _reachable_targets(
    source: str,
    targets: set[str],
    outgoing: Mapping[str, Sequence[str]],
) -> set[str]:
    """Return only requested graph targets reachable after ``source``."""

    found: set[str] = set()
    pending = deque(outgoing.get(source, ()))
    seen = {source}
    while pending and found != targets:
        node_id = pending.popleft()
        if node_id in seen:
            continue
        seen.add(node_id)
        if node_id in targets:
            found.add(node_id)
        pending.extend(outgoing.get(node_id, ()))
    return found


def _state_write_may_set_read(
    read_expression: str,
    variable: str,
    operator: str,
    write_expression: str,
) -> bool:
    """Match direct equality gates without attempting symbolic state solving."""

    if operator != "=":
        return True
    equality = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(variable)}\s*==\s*"
        r"(?P<value>True|False|None|-?\d+(?:\.\d+)?|'[^']*'|\"[^\"]*\")"
    )
    expected_values = {match.group("value") for match in equality.finditer(read_expression)}
    if not expected_values:
        return True
    return write_expression.strip() in expected_values


def _effect_text(mechanic: Mapping[str, object]) -> str:
    fact = _mapping(mechanic.get("state_effect"), "state effect")
    return (
        f"{_text(fact.get('variable'), 'effect variable')} "
        f"{_text(fact.get('operator'), 'effect operator')} "
        f"{_text(fact.get('expression'), 'effect expression')}"
    )


def _flow_order(
    graph: Mapping[str, object],
    nodes: Mapping[str, Mapping[str, object]],
    edges: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    entry_label = _text(graph.get("entry_label"), "entry label")
    entry = next(
        node_id
        for node_id, node in nodes.items()
        if node.get("kind") == "label" and node.get("label") == entry_label
    )
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        outgoing[_text(edge.get("source"), "edge source")].append(
            _text(edge.get("target"), "edge target")
        )
    pending = deque([entry])
    result: dict[str, int] = {}
    while pending:
        node_id = pending.popleft()
        if node_id in result:
            continue
        result[node_id] = len(result)
        pending.extend(
            sorted(
                outgoing.get(node_id, ()),
                key=lambda item: (_source_sort(nodes[item]), item),
            )
        )
    return result


def _region_depths(regions: Mapping[str, Mapping[str, object]]) -> dict[str, int]:
    result: dict[str, int] = {}

    def depth(region_id: str, seen: frozenset[str] = frozenset()) -> int:
        if region_id in result:
            return result[region_id]
        if region_id in seen:
            raise ValueError("M06 region parent cycle")
        parent = regions[region_id].get("parent_region_id")
        value = 0 if not isinstance(parent, str) else depth(parent, seen | {region_id}) + 1
        result[region_id] = value
        return value

    for region_id in regions:
        depth(region_id)
    return result


def _label_source(
    label: str,
    nodes: Mapping[str, Mapping[str, object]],
    flow_order: Mapping[str, int],
) -> dict[str, object]:
    node = min(
        (item for item in nodes.values() if item.get("label") == label),
        key=lambda item: flow_order.get(_text(item.get("id"), "label node"), 10**9),
    )
    return _flat_source(node)


def _binding(
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
        "source": _reader_source(source),
    }


def _reader_source(source: Mapping[str, object]) -> dict[str, object]:
    return {
        "relative_path": _text(source.get("path"), "source path"),
        "start_line": _integer(source.get("start_line"), "source start line"),
        "end_line": _integer(source.get("end_line"), "source end line"),
    }


def _flat_source(node: Mapping[str, object]) -> dict[str, object]:
    source = _mapping(node.get("source"), "node source")
    if "start_line" in source:
        return dict(source)
    start = _mapping(source.get("start"), "source start")
    end = _mapping(source.get("end"), "source end")
    return {
        "path": _text(source.get("path"), "source path"),
        "start_line": _integer(start.get("line"), "source start line"),
        "start_column": _integer(start.get("column"), "source start column"),
        "end_line": _integer(end.get("line"), "source end line"),
        "end_column": _integer(end.get("column"), "source end column"),
    }


def _source_sort(node: Mapping[str, object]) -> tuple[str, int, int]:
    source = _flat_source(node)
    return (
        _text(source.get("path"), "source path"),
        _integer(source.get("start_line"), "source line"),
        _integer(source.get("start_column"), "source column"),
    )


def _accepted_story_names(value: Mapping[str, object] | None) -> dict[str, str]:
    if value is None:
        return {}
    raw_names = value.get("names") if "names" in value else value
    names = _mapping(raw_names, "story name overrides")
    accepted: dict[str, str] = {}
    for stable_id, raw_name in names.items():
        name = _text(raw_name, f"story name override {stable_id}").strip()
        if not _safe_story_name(name):
            raise ValueError(f"story name override {stable_id} is machine-facing")
        accepted[stable_id] = name
    return accepted


def _resolve_story_name(
    *,
    stable_id: str,
    overrides: Mapping[str, str],
    exact_title: str | None = None,
    owning_title: str | None = None,
    first_line: str | None = None,
    fallback: str = _UNNAMED_ROUTE,
) -> tuple[str, str]:
    candidates = (
        ("accepted_override", overrides.get(stable_id)),
        ("exact_corridor_title", exact_title),
        ("owning_event_title", owning_title),
        ("first_readable_narrative", first_line),
    )
    for source, candidate in candidates:
        if isinstance(candidate, str) and _safe_story_name(candidate):
            return candidate.strip(), source
    return fallback, "fallback"


def _safe_story_name(value: str | None) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = value.strip()
    if candidate in {_UNNAMED_ROUTE, _UNRESOLVED_DESTINATION, "Otherwise"}:
        return False
    lowered = candidate.casefold()
    if lowered.startswith(("if ", "elif ", "else:", "check whether", "routes:")):
        return False
    if "shared " in lowered and " continuation" in lowered:
        return False
    if "`" in candidate:
        return False
    if _MACHINE_IDENTIFIER.search(candidate):
        return False
    return not any(
        token in candidate for token in (" = ", " == ", " != ", " >= ", " <= ")
    )


def _visible_story_prose(value: str, *, fallback: str) -> str:
    chunks = re.split(r"(?<=[.!?])\s+|\n+", value.strip())
    readable = [chunk.strip() for chunk in chunks if _safe_story_prose(chunk)]
    return " ".join(readable) if readable else fallback


def _safe_story_prose(value: str) -> bool:
    if not value:
        return False
    if "`" in value or _MACHINE_IDENTIFIER.search(value):
        return False
    return not re.search(r"(?:==|!=|>=|<=)|\b(?:True|False|None)\b", value)


def _first_readable_story_line(packets: Sequence[Mapping[str, object]]) -> str | None:
    for packet in packets:
        story_text = packet.get("story_text")
        if not isinstance(story_text, str):
            continue
        for raw_line in story_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            _speaker, separator, spoken = line.partition(":")
            candidate = spoken.strip() if separator else line
            candidate = candidate.strip().strip('"').strip()
            if _safe_story_name(candidate):
                return candidate
    return None


def _first_packet_title(
    packets: Sequence[Mapping[str, object]],
    results: Mapping[str, Mapping[str, object]],
) -> str | None:
    for packet in packets:
        corridor_id = _text(packet.get("corridor_id"), "name corridor")
        title = results[corridor_id].get("title")
        if isinstance(title, str) and _safe_story_name(title):
            return title.strip()
    return None


def _unique_text(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _index(
    value: Mapping[str, object], collection: str, key: str
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for raw in _list(value.get(collection), collection):
        item = _mapping(raw, collection[:-1])
        identity = _text(item.get(key), f"{collection} {key}")
        if identity in result:
            raise ValueError(f"duplicate {collection} {identity}")
        result[identity] = item
    return result


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
