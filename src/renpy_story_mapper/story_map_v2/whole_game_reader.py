"""Whole-game reader assembly over Phase 05 Python facts and approved AI prose."""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from typing import cast

from renpy_story_mapper.story_map_v2.progressive_story import PHASE05_PROGRESSIVE_MARKER

WHOLE_GAME_READER_MARKER = f"{PHASE05_PROGRESSIVE_MARKER}: whole-game reader"
_CONTROL_KINDS = frozenset({"menu", "if"})


def build_whole_game_reader_page(
    graph: Mapping[str, object],
    control_flow: Mapping[str, object],
    skeleton: Mapping[str, object],
    corridors: Mapping[str, object],
    summaries: Mapping[str, object],
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
    for packet in packets:
        label = _text(packet.get("owning_label"), "packet label")
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

    for values in (*controls_by_label.values(), *children_by_arm.values()):
        values.sort(key=lambda node_id: flow_order.get(node_id, 10**9))
    for values in (*packets_by_label.values(), *packets_by_arm.values()):
        values.sort(key=lambda packet: packet_order[_text(packet.get("corridor_id"), "packet")])

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

    projected_controls: set[str] = set()

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
        return {
            "key": f"story:{_control_title(control, projected_arms)}",
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
        merge_id = (
            region.get("merge_node_id") if isinstance(region.get("merge_node_id"), str) else None
        )
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
        caption, condition = _arm_caption(control, entry)
        effect_text = [_effect_text(item) for item in effects_by_arm.get(arm_id, ())]
        rejoin_title = (
            merge_titles.get(merge_id) or f"Shared {_humanize(label)} continuation"
            if merge_id
            else None
        )
        if assigned:
            _title, outline, detail = _prose(assigned, results)
        else:
            outline = _structure_arm_summary(
                destination=destination,
                rejoin_title=rejoin_title,
                outcome=outcome,
                nested_choices=children,
                label=label,
                effects=effect_text,
            )
            detail = outline
        secondary_notes = secondary_by_arm.get(arm_id, ())
        if secondary_notes:
            detail = f"{detail}\n\nTechnical controls\n" + "\n".join(secondary_notes)
        reads = [
            _mapping(item, "state read") for item in _list(arm.get("state_reads"), "state reads")
        ]
        warnings = []
        if unresolved:
            warnings.append("Python marked unresolved behavior on this route.")
        if reads:
            variables = sorted(
                {_text(item.get("variable"), "state read variable") for item in reads}
            )
            warnings.append(f"Earlier state controls this route: {', '.join(variables)}.")
        source = _flat_source(entry)
        selection_id = f"whole-game:arm:{arm_id}"
        binding_target = destination or entry_id
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
        return {
            "selection_id": selection_id,
            "caption": caption,
            "outcome_kind": outcome,
            "outcome_summary": outline,
            "outline_summary": outline,
            "detail_summary": detail,
            "condition": condition,
            "effects": effect_text,
            "destination_id": f"story:{_humanize(destination)}" if destination else entry_id,
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
                f"story:{_humanize(binding_target)}" if destination else entry_id,
                "story_map_v2_arm",
                source,
            ),
            "rejoin_binding": rejoin_binding,
            "nested_choices": children,
        }

    events: list[dict[str, object]] = []
    included_corridors: list[str] = []
    for label in label_order:
        assigned = packets_by_label.get(label, [])
        choices = [
            project_choice(control_id, label, frozenset())
            for control_id in controls_by_label.get(label, ())
        ]
        if assigned:
            title, outline, detail = _prose(assigned, results)
        else:
            title = (
                f"Routes: {_projected_control_title(choices[0])}" if choices else _humanize(label)
            )
            outline = ""
            detail = ""
        source = _label_source(label, nodes, flow_order)
        selection_id = f"whole-game:label:{label}"
        label_effects = [_effect_text(item) for item in effects_by_label.get(label, ())]
        if label_effects:
            detail = f"{detail}\n\nState changes\n" + "\n".join(label_effects)
        secondary_notes = secondary_by_label.get(label, ())
        if secondary_notes:
            detail = f"{detail}\n\nTechnical controls\n" + "\n".join(secondary_notes)
        included_corridors.extend(
            _text(packet.get("corridor_id"), "event corridor") for packet in assigned
        )
        events.append(
            {
                "selection_id": selection_id,
                "title": title,
                "summary": outline,
                "outline_summary": outline,
                "detail_summary": detail,
                "characters": [],
                "reachability": "reachable",
                "warnings": [f"Python label: {label}"],
                "binding": _binding(
                    selection_id,
                    "generic_scene",
                    f"story:{_humanize(label)}",
                    "story_map_v2_event",
                    source,
                ),
                "choices": choices,
            }
        )

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

    low_ids = {
        corridor_id
        for corridor_id, result in results.items()
        if result.get("packet_shape_grade") == "LOW" and corridor_id not in excluded
    }
    counts = _mapping(corridors.get("counts"), "corridor counts")
    page = {
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
                f"{len(events)} Python label continuations and their owning route arms."
            ),
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
    title = _text(preferred.get("title"), "prose title")
    outline = _text(preferred.get("summary"), "prose summary")
    detail_parts: list[str] = []
    for item in values:
        item_title = _text(item.get("title"), "detail title")
        detail_parts.append(f"{item_title}\n{_text(item.get('detail'), 'detail prose')}")
        for raw_child in _list(item.get("presentation_children"), "presentation children"):
            child = _mapping(raw_child, "presentation child")
            detail_parts.append(
                f"{_text(child.get('title'), 'child title')} — "
                f"{_text(child.get('summary'), 'child summary')}"
            )
    return title, outline, "\n\n".join(detail_parts)


def _projected_control_title(choice: Mapping[str, object]) -> str:
    key = _text(choice.get("key"), "projected control key")
    return key.removeprefix("story:").strip()


def _structure_arm_summary(
    *,
    destination: str | None,
    rejoin_title: str | None,
    outcome: str,
    nested_choices: Sequence[Mapping[str, object]],
    label: str,
    effects: Sequence[str],
) -> str:
    if destination:
        return f"Continues to {_humanize(destination)}."
    if nested_choices:
        titles = [_projected_control_title(choice) for choice in nested_choices]
        return f"Next: {'; '.join(titles)}."
    if rejoin_title:
        return f"Rejoins at {rejoin_title}."
    if outcome == "ends":
        return f"Ends at {_humanize(label)}."
    if outcome == "unresolved":
        return f"Unresolved at {_humanize(label)}."
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


def _control_title(control: Mapping[str, object], arms: Sequence[Mapping[str, object]]) -> str:
    if control.get("kind") == "if":
        raw = _text(control.get("source_text"), "condition source").strip()
        condition = raw[3:-1].strip() if raw.startswith("if ") and raw.endswith(":") else raw
        return f"Check whether {condition}"
    captions = [_text(arm.get("caption"), "projected arm caption") for arm in arms]
    return " / ".join(captions)


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


def _humanize(value: str | None) -> str:
    if not value:
        return "Story continuation"
    words = value.strip("_").replace(".secondpart", " continuation").split("_")
    readable = " ".join(word for word in words if word and word not in {"clean", "neutral"})
    return readable or value


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
