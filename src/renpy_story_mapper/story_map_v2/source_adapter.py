"""Adapt stable deterministic authority into the compact Story Map V2 scope.

The adapter deliberately emits no provider atoms, evidence allocation, or generated
narrative records.  M10 remains authoritative; M11 is used only as an optional source-order
and natural-boundary hint after its binding is verified.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from renpy_story_mapper.canonical_graph_contract import (
    CanonicalEdge,
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeKind,
    CanonicalRegion,
    ReachabilityStatus,
    SourceEvidence,
)
from renpy_story_mapper.m11_scene_model import SceneModel
from renpy_story_mapper.story_map_v2.contracts import (
    ArmLineageStep,
    ArmMechanic,
    ChoiceMechanic,
    Reachability,
    SourceSpan,
    StoryScope,
    canonical_hash,
)

_QUOTED_CAPTION = re.compile(r"^\s*([\"'])(.*?)\1")
_PROVEN_REJOIN_KINDS = {
    "local_detour",
    "optional_detour",
    "reconvergent_route_segment",
}


class SourceAdaptationError(ValueError):
    """The supplied deterministic records cannot form an honest StoryScope."""


@dataclass(frozen=True)
class _LocatedNode:
    node: CanonicalNode
    evidence: SourceEvidence
    path: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class _ChoiceRegion:
    region: CanonicalRegion
    key: str
    path: str
    line: int
    depth: int
    parent_origin_id: str | None
    arm_members: tuple[frozenset[str], ...]
    mechanic: ChoiceMechanic


def adapt_story_scope(
    graph: CanonicalGraph,
    *,
    source_identity: str | None = None,
    scene_model: SceneModel | None = None,
) -> StoryScope:
    """Project M10 authority into one source-ordered, provider-neutral story scope.

    ``scene_model`` is optional.  When supplied, it contributes only existing canonical-node
    order and scene boundaries; it never contributes provider-facing atom IDs or membership.
    """

    graph.validate()
    if scene_model is not None:
        _validate_scene_binding(graph, scene_model)

    evidence_by_id = {item.id: item for item in graph.evidence}
    located = _located_nodes(graph.nodes, evidence_by_id)
    if not located:
        raise SourceAdaptationError("canonical authority has no physical source spans")

    located_by_node = {item.node.id: item for item in located}
    choices = _choice_regions(graph, located_by_node)
    ordered = sorted(located, key=_source_order_key(scene_model))
    boundary_nodes = _natural_boundary_nodes(scene_model)
    spans = _source_spans(
        ordered,
        choices,
        boundary_nodes=boundary_nodes,
        source_generation=graph.source_generation,
    )
    identity = source_identity or canonical_hash(
        {
            "source_generation": graph.source_generation,
            "canonical_hash": graph.authority_hash,
        }
    )
    if not identity or identity != identity.strip():
        raise SourceAdaptationError("source identity must be a non-empty trimmed string")
    return StoryScope(
        source_identity=identity,
        source_generation=graph.source_generation,
        canonical_hash=graph.authority_hash,
        spans=spans,
        choices=tuple(item.mechanic for item in sorted(choices, key=_choice_sort_key)),
    )


def _validate_scene_binding(graph: CanonicalGraph, scene_model: SceneModel) -> None:
    binding = scene_model.binding
    if (
        binding.source_generation != graph.source_generation
        or binding.canonical_hash != graph.authority_hash
    ):
        raise SourceAdaptationError("M11 scene binding does not match M10 authority")


def _located_nodes(
    nodes: Sequence[CanonicalNode],
    evidence_by_id: Mapping[str, SourceEvidence],
) -> tuple[_LocatedNode, ...]:
    result: list[_LocatedNode] = []
    for node in nodes:
        if node.attributes.get("synthetic") is True:
            continue
        candidates: list[_LocatedNode] = []
        for evidence_id in node.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                continue
            location = _source_location(evidence.source)
            if location is None:
                continue
            path, start_line, end_line = location
            candidates.append(_LocatedNode(node, evidence, path, start_line, end_line))
        if candidates:
            result.append(
                min(
                    candidates,
                    key=lambda item: (
                        item.path,
                        item.start_line,
                        item.end_line,
                        item.evidence.id,
                    ),
                )
            )
    return tuple(result)


def _source_location(source: Mapping[str, object]) -> tuple[str, int, int] | None:
    path_value = source.get("path", source.get("relative_path"))
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    path = PurePosixPath(path_value.replace("\\", "/")).as_posix()
    start_value = source.get("start")
    end_value = source.get("end")
    start = (
        start_value.get("line") if isinstance(start_value, Mapping) else source.get("start_line")
    )
    end = end_value.get("line") if isinstance(end_value, Mapping) else source.get("end_line")
    if not _positive_int(start):
        return None
    end_line = end if _positive_int(end) else start
    assert isinstance(start, int) and isinstance(end_line, int)
    if end_line < start:
        return None
    return path, start, end_line


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _choice_regions(
    graph: CanonicalGraph,
    located_by_node: Mapping[str, _LocatedNode],
) -> tuple[_ChoiceRegion, ...]:
    nodes = {item.id: item for item in graph.nodes}
    edges = {item.id: item for item in graph.edges}
    facts = {item.id: item for item in graph.facts}
    origin_to_region = {
        origin.record_id: region
        for region in graph.regions
        for origin in region.origins
        if origin.collection == "m06_control_flow"
    }
    depth_by_region = {
        region.id: _region_depth(region, origin_to_region) for region in graph.regions
    }
    children_by_region: dict[str, list[CanonicalRegion]] = defaultdict(list)
    for candidate in graph.regions:
        parent_origin = candidate.attributes.get("parent_region_id")
        parent = origin_to_region.get(parent_origin) if isinstance(parent_origin, str) else None
        if parent is not None:
            children_by_region[parent.id].append(candidate)
    provisional: list[tuple[CanonicalRegion, str, str, int, tuple[Mapping[str, object], ...]]] = []
    for region in graph.regions:
        split = nodes.get(region.split_node_id)
        split_location = located_by_node.get(region.split_node_id)
        if split is None or split_location is None or split.attributes.get("source_kind") != "menu":
            continue
        raw_arms = region.attributes.get("arms")
        if not isinstance(raw_arms, Sequence) or isinstance(raw_arms, (str, bytes)):
            continue
        arms = tuple(
            item for item in raw_arms if isinstance(item, Mapping) and _is_displayed_menu_arm(item)
        )
        if not arms:
            continue
        key = f"{split_location.path}:{split_location.start_line}"
        provisional.append((region, key, split_location.path, split_location.start_line, arms))

    key_by_region = {region.id: key for region, key, _path, _line, _arms in provisional}
    arm_members_by_region = {
        region.id: tuple(
            _expanded_arm_members(region, raw_arm, children_by_region)
            for raw_arm in sorted(raw_arms, key=lambda item: _required_ordinal(item, "ordinal"))
        )
        for region, _key, _path, _line, raw_arms in provisional
    }
    result: list[_ChoiceRegion] = []
    for region, key, path, line, raw_arms in provisional:
        parent_lineage = _lineage_for_node(
            region.split_node_id,
            provisional,
            key_by_region,
            depth_by_region,
            arm_members_by_region,
        )
        mechanics: list[ArmMechanic] = []
        member_sets = arm_members_by_region[region.id]
        for expected_order, (raw_arm, member_ids) in enumerate(
            zip(
                sorted(raw_arms, key=lambda item: _required_ordinal(item, "ordinal")),
                member_sets,
                strict=True,
            ),
            start=1,
        ):
            mechanics.append(
                _arm_mechanic(
                    region,
                    raw_arm,
                    member_ids,
                    expected_order,
                    nodes,
                    edges,
                    facts,
                    located_by_node,
                )
            )
        parent_origin = region.attributes.get("parent_region_id")
        result.append(
            _ChoiceRegion(
                region=region,
                key=key,
                path=path,
                line=line,
                depth=depth_by_region[region.id],
                parent_origin_id=parent_origin if isinstance(parent_origin, str) else None,
                arm_members=member_sets,
                mechanic=ChoiceMechanic(
                    key=key,
                    relative_path=path,
                    line=line,
                    arms=tuple(mechanics),
                    parent_lineage=parent_lineage,
                    story_choice=_is_story_choice(member_sets, nodes, edges, mechanics),
                ),
            )
        )
    return tuple(result)


def _is_displayed_menu_arm(arm: Mapping[str, object]) -> bool:
    predicate = arm.get("predicate")
    return isinstance(predicate, Mapping) and predicate.get("kind") == "menu_choice"


def _expanded_arm_members(
    region: CanonicalRegion,
    raw_arm: Mapping[str, object],
    children_by_region: Mapping[str, Sequence[CanonicalRegion]],
) -> frozenset[str]:
    members = {
        *_string_sequence(raw_arm.get("member_node_ids")),
        _required_text(raw_arm, "entry_node_id"),
    }

    def include_descendants(parent: CanonicalRegion) -> None:
        for child in children_by_region.get(parent.id, ()):
            child_members = _region_member_ids(child)
            if not members.intersection(child_members):
                continue
            members.update(child_members)
            include_descendants(child)

    include_descendants(region)
    return frozenset(members)


def _region_member_ids(region: CanonicalRegion) -> set[str]:
    members = {
        region.split_node_id,
        *_string_sequence(region.attributes.get("member_node_ids")),
    }
    if region.merge_node_id is not None:
        members.add(region.merge_node_id)
    raw_arms = region.attributes.get("arms")
    if isinstance(raw_arms, Sequence) and not isinstance(raw_arms, (str, bytes)):
        for raw_arm in raw_arms:
            if not isinstance(raw_arm, Mapping):
                continue
            members.update(_string_sequence(raw_arm.get("member_node_ids")))
            entry = raw_arm.get("entry_node_id")
            if isinstance(entry, str) and entry:
                members.add(entry)
    return members


def _region_depth(
    region: CanonicalRegion,
    origin_to_region: Mapping[str, CanonicalRegion],
) -> int:
    depth = 0
    seen: set[str] = set()
    parent = region.attributes.get("parent_region_id")
    while isinstance(parent, str) and parent not in seen:
        seen.add(parent)
        parent_region = origin_to_region.get(parent)
        if parent_region is None:
            break
        depth += 1
        parent = parent_region.attributes.get("parent_region_id")
    return depth


def _lineage_for_node(
    node_id: str,
    choices: Sequence[tuple[CanonicalRegion, str, str, int, tuple[Mapping[str, object], ...]]],
    key_by_region: Mapping[str, str],
    depth_by_region: Mapping[str, int],
    arm_members_by_region: Mapping[str, tuple[frozenset[str], ...]],
) -> tuple[ArmLineageStep, ...]:
    steps: list[tuple[int, ArmLineageStep]] = []
    for region, _key, _path, _line, _raw_arms in choices:
        for ordinal, members in enumerate(arm_members_by_region[region.id], start=1):
            if node_id in members:
                steps.append(
                    (
                        depth_by_region[region.id],
                        ArmLineageStep(key_by_region[region.id], ordinal),
                    )
                )
                break
    return tuple(step for _depth, step in sorted(steps, key=lambda item: (item[0], item[1])))


def _arm_mechanic(
    region: CanonicalRegion,
    raw_arm: Mapping[str, object],
    member_ids: frozenset[str],
    order: int,
    nodes: Mapping[str, CanonicalNode],
    edges: Mapping[str, CanonicalEdge],
    facts: Mapping[str, object],
    located_by_node: Mapping[str, _LocatedNode],
) -> ArmMechanic:
    entry_id = _required_text(raw_arm, "entry_node_id")
    edge_id = _required_text(raw_arm, "edge_id")
    entry = nodes[entry_id]
    edge = edges[edge_id]
    entry_location = located_by_node.get(entry_id)
    if entry_location is None:
        raise SourceAdaptationError(f"choice arm {entry_id} lacks physical source evidence")
    locations = [located_by_node[item] for item in member_ids if item in located_by_node]
    same_path = [item for item in locations if item.path == entry_location.path]
    end_line = max((item.end_line for item in same_path), default=entry_location.end_line)
    rejoin_node_id, rejoin_line = _proven_rejoin(region, located_by_node)
    fact_ids: set[str] = set()
    for node_id in member_ids:
        node = nodes.get(node_id)
        if node is not None:
            fact_ids.update(_string_sequence(node.attributes.get("fact_ids")))
    for candidate in edges.values():
        if candidate.source_id in member_ids or candidate.target_id in member_ids:
            fact_ids.update(_string_sequence(candidate.attributes.get("effect_ids")))
    effects: list[str] = []
    warnings: list[str] = []
    for fact_id in sorted(fact_ids):
        fact = facts.get(fact_id)
        kind = getattr(fact, "kind", None)
        status = getattr(fact, "status", None)
        attributes = getattr(fact, "attributes", {})
        if kind == "effect" and isinstance(attributes, Mapping):
            expression = attributes.get("original_expression")
            if isinstance(expression, str) and expression.strip():
                effects.append(expression.strip())
        if status in {"possible", "unresolved"}:
            warnings.append(f"{status} fact {fact_id}")
    if raw_arm.get("unresolved") is True:
        warnings.append("arm has unresolved static behavior")
    if edge.reachability is ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR:
        warnings.append("arm reachability depends on unresolved dynamic behavior")
    return ArmMechanic(
        order=order,
        caption=_caption(entry),
        start_line=entry_location.start_line,
        end_line=end_line,
        condition=_condition(raw_arm.get("predicate")),
        effects=tuple(dict.fromkeys(effects)),
        destination_id=entry_id,
        rejoin_node_id=rejoin_node_id,
        rejoin_line=rejoin_line,
        reachability=_reachability(edge.reachability),
        unresolved_warnings=tuple(dict.fromkeys(warnings)),
    )


def _caption(node: CanonicalNode) -> str:
    metadata = node.attributes.get("metadata")
    if isinstance(metadata, Mapping):
        value = metadata.get("caption")
        if isinstance(value, str) and value.strip():
            return value.strip()
    source_text = node.attributes.get("source_text")
    if isinstance(source_text, str):
        match = _QUOTED_CAPTION.match(source_text)
        if match is not None and match.group(2).strip():
            return match.group(2).strip()
    raise SourceAdaptationError(f"choice arm {node.id} lacks an exact caption")


def _condition(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    expression = value.get("expression")
    if isinstance(expression, str) and expression.strip():
        return expression.strip()
    conditions = value.get("conditions")
    if not isinstance(conditions, Sequence) or isinstance(conditions, (str, bytes)):
        return None
    rendered: list[str] = []
    for condition in conditions:
        if not isinstance(condition, Mapping):
            continue
        item = condition.get("expression")
        if not isinstance(item, str) or not item.strip():
            continue
        rendered.append(
            f"not ({item.strip()})" if condition.get("polarity") == "negative" else item.strip()
        )
    return " and ".join(rendered) or None


def _proven_rejoin(
    region: CanonicalRegion,
    located_by_node: Mapping[str, _LocatedNode],
) -> tuple[str | None, int | None]:
    if region.merge_node_id is None or region.kind not in _PROVEN_REJOIN_KINDS:
        return None, None
    location = located_by_node.get(region.merge_node_id)
    return region.merge_node_id, location.start_line if location is not None else None


def _reachability(value: ReachabilityStatus) -> Reachability:
    if value is ReachabilityStatus.PROVEN_UNREACHABLE:
        return Reachability.UNREACHABLE
    if value in {
        ReachabilityStatus.PROVEN_REACHABLE,
        ReachabilityStatus.CONDITIONALLY_REACHABLE,
        ReachabilityStatus.REACHABLE_UNDER_INFERRED_REQUIREMENTS,
    }:
        return Reachability.REACHABLE
    return Reachability.UNRESOLVED


def _is_story_choice(
    arm_members: Sequence[frozenset[str]],
    nodes: Mapping[str, CanonicalNode],
    edges: Mapping[str, CanonicalEdge],
    arms: Sequence[ArmMechanic],
) -> bool:
    """Require canonical story or route authority, not captions or arm-count guesses."""

    source_kinds = {
        node.attributes.get("source_kind")
        for members in arm_members
        for node_id in members
        for node in (nodes.get(node_id),)
        if node is not None
    }
    if "statement" in source_kinds:
        return True
    rejoin_ids = {arm.rejoin_node_id for arm in arms}
    has_shared_local_rejoin = len(rejoin_ids) == 1 and None not in rejoin_ids
    if not has_shared_local_rejoin:
        return bool(source_kinds.intersection({"jump", "call", "return"}))
    narrative_call_targets = tuple(
        _narrative_call_targets(members, nodes, edges) for members in arm_members
    )
    return any(narrative_call_targets) and len(set(narrative_call_targets)) > 1


def _narrative_call_targets(
    member_ids: frozenset[str],
    nodes: Mapping[str, CanonicalNode],
    edges: Mapping[str, CanonicalEdge],
) -> tuple[str, ...]:
    outgoing: dict[str, list[CanonicalEdge]] = defaultdict(list)
    for edge in edges.values():
        outgoing[edge.source_id].append(edge)
    targets = {
        edge.target_id
        for node_id in member_ids
        if (node := nodes.get(node_id)) is not None and node.attributes.get("source_kind") == "call"
        for edge in outgoing.get(node_id, ())
        if edge.kind == "call_enter" and _reachability(edge.reachability) is Reachability.REACHABLE
    }
    return tuple(
        sorted(
            story_node_id
            for target in targets
            for story_node_id in _target_story_content_ids(target, nodes, outgoing)
        )
    )


def _target_story_content_ids(
    target_id: str,
    nodes: Mapping[str, CanonicalNode],
    outgoing: Mapping[str, Sequence[CanonicalEdge]],
) -> frozenset[str]:
    pending = [target_id]
    visited: set[str] = set()
    story_nodes: set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        node = nodes.get(node_id)
        if node is None:
            continue
        if (
            node.attributes.get("source_kind") == "statement"
            and _reachability(node.reachability) is Reachability.REACHABLE
        ):
            story_nodes.add(node_id)
        pending.extend(
            edge.target_id
            for edge in outgoing.get(node_id, ())
            if _reachability(edge.reachability) is Reachability.REACHABLE
        )
    return frozenset(story_nodes)


def _source_order_key(scene_model: SceneModel | None):  # type: ignore[no-untyped-def]
    if scene_model is None:
        return lambda item: (item.path, item.start_line, item.end_line, item.node.id)
    atom_by_id = {item.id: item for item in scene_model.atoms}
    rank: dict[str, int] = {}
    cursor = 0
    for chapter in sorted(scene_model.chapters, key=lambda item: (item.ordinal, item.id)):
        scene_by_id = {item.id: item for item in scene_model.scenes}
        for scene_id in chapter.scene_ids:
            scene = scene_by_id.get(scene_id)
            if scene is None:
                continue
            for atom_id in scene.atom_ids:
                atom = atom_by_id.get(atom_id)
                if atom is not None and atom.primary_node_id not in rank:
                    rank[atom.primary_node_id] = cursor
                    cursor += 1
    return lambda item: (
        rank.get(item.node.id, cursor),
        item.path,
        item.start_line,
        item.end_line,
        item.node.id,
    )


def _natural_boundary_nodes(scene_model: SceneModel | None) -> set[str]:
    if scene_model is None:
        return set()
    atom_by_id = {item.id: item for item in scene_model.atoms}
    result: set[str] = set()
    for scene in scene_model.scenes:
        if not scene.atom_ids:
            continue
        atom = atom_by_id.get(scene.atom_ids[-1])
        if atom is not None:
            result.add(atom.primary_node_id)
    return result


def _source_spans(
    located: Sequence[_LocatedNode],
    choices: Sequence[_ChoiceRegion],
    *,
    boundary_nodes: set[str],
    source_generation: str,
) -> tuple[SourceSpan, ...]:
    grouped: dict[tuple[str, int, int, str], list[_LocatedNode]] = defaultdict(list)
    for item in located:
        text = item.evidence.source_text or str(item.node.attributes.get("source_text", ""))
        grouped[(item.path, item.start_line, item.end_line, text)].append(item)
    result: list[SourceSpan] = []
    for (path, start, end, text), items in grouped.items():
        node_ids = tuple(sorted({item.node.id for item in items}))
        lineage = _span_lineage(node_ids, choices)
        choice_keys = _span_choice_keys(node_ids, choices)
        shared = any(choice.region.merge_node_id in node_ids for choice in choices)
        kinds = {item.node.kind for item in items}
        reachability, unresolved_warnings = _span_reachability(items)
        natural = bool(boundary_nodes.intersection(node_ids)) or bool(
            kinds
            & {
                CanonicalNodeKind.LABEL_REGION,
                CanonicalNodeKind.MERGE,
                CanonicalNodeKind.TERMINAL,
            }
        )
        numbered = _line_numbered(text, start)
        key = (
            "span_"
            + canonical_hash(
                {
                    "source_generation": source_generation,
                    "path": path,
                    "start": start,
                    "end": end,
                    "canonical_node_ids": node_ids,
                }
            )[:20]
        )
        result.append(
            SourceSpan(
                key=key,
                relative_path=path,
                start_line=start,
                end_line=end,
                raw_text=numbered,
                estimated_tokens=_estimate_tokens(text),
                canonical_node_ids=node_ids,
                reachability=reachability,
                unresolved_warnings=unresolved_warnings,
                choice_keys=choice_keys,
                arm_lineage=lineage,
                natural_boundary_after=natural,
                shared_continuation=shared,
            )
        )
    order = {item.node.id: index for index, item in enumerate(located)}
    result.sort(
        key=lambda span: (
            min((order.get(node_id, len(order)) for node_id in span.canonical_node_ids), default=0),
            span.relative_path,
            span.start_line,
            span.key,
        )
    )
    return tuple(result)


def _span_reachability(
    items: Sequence[_LocatedNode],
) -> tuple[Reachability, tuple[str, ...]]:
    """Aggregate exact M10 statuses without turning mixed authority into certainty."""

    statuses = tuple(item.node.reachability for item in items)
    projected = tuple(_reachability(status) for status in statuses)
    if projected and all(value is Reachability.REACHABLE for value in projected):
        return Reachability.REACHABLE, ()
    if projected and all(value is Reachability.UNREACHABLE for value in projected):
        return Reachability.UNREACHABLE, ()
    warnings = tuple(
        dict.fromkeys(
            f"canonical node {item.node.id} has unresolved reachability: "
            f"{item.node.reachability.value}"
            for item in items
            if _reachability(item.node.reachability) is Reachability.UNRESOLVED
        )
    )
    if not warnings:
        warnings = ("covered canonical nodes have mixed reachability",)
    return Reachability.UNRESOLVED, warnings


def _span_lineage(
    node_ids: Sequence[str], choices: Sequence[_ChoiceRegion]
) -> tuple[ArmLineageStep, ...]:
    lineages = {_node_lineage(node_id, choices) for node_id in node_ids}
    if len(lineages) == 1:
        return next(iter(lineages))
    return ()


def _node_lineage(node_id: str, choices: Sequence[_ChoiceRegion]) -> tuple[ArmLineageStep, ...]:
    steps: list[ArmLineageStep] = []
    for choice in sorted(choices, key=_choice_sort_key):
        for ordinal, members in enumerate(choice.arm_members, start=1):
            if node_id in members:
                for step in (
                    *choice.mechanic.parent_lineage,
                    ArmLineageStep(choice.key, ordinal),
                ):
                    if step not in steps:
                        steps.append(step)
                break
    return tuple(steps)


def _span_choice_keys(node_ids: Sequence[str], choices: Sequence[_ChoiceRegion]) -> tuple[str, ...]:
    keys: list[tuple[int, str]] = []
    node_set = set(node_ids)
    for choice in choices:
        involved = (
            choice.region.split_node_id in node_set
            or choice.region.merge_node_id in node_set
            or any(node_set & members for members in choice.arm_members)
        )
        if involved:
            keys.append((choice.depth, choice.key))
    return tuple(key for _depth, key in sorted(set(keys)))


def _line_numbered(text: str, start_line: int) -> str:
    lines = text.splitlines() or [text]
    return "".join(f"{start_line + offset}: {line}\n" for offset, line in enumerate(lines))


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text.encode("utf-8")) + 3) // 4)


def _choice_sort_key(item: _ChoiceRegion) -> tuple[int, str, int, str]:
    return item.depth, item.path, item.line, item.key


def _required_text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise SourceAdaptationError(f"branch arm requires {key}")
    return item


def _required_ordinal(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise SourceAdaptationError(f"branch arm requires non-negative {key}")
    assert isinstance(item, int)
    return item


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)
