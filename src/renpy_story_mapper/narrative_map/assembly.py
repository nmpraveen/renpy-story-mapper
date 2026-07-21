"""Fail-closed deterministic assembly of complete M15 Narrative Events."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import cast, overload

from renpy_story_mapper.canonical_graph_contract import (
    CanonicalEdge,
    CanonicalGraph,
    CanonicalNode,
    CanonicalRegion,
)
from renpy_story_mapper.m11_scene_model import SceneModel
from renpy_story_mapper.narrative_map.adapters import ordered_unique
from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    BoundaryDecision,
    BoundaryDecisionKind,
    CoverageState,
    EvidenceNavigation,
    NarrativeCorridor,
    NarrativeEvent,
    Provenance,
    SourceLocator,
    canonical_hash,
    stable_m15_id,
)
from renpy_story_mapper.narrative_map.corridors import (
    build_all_eligible_gap_candidates,
    build_boundary_candidates,
    build_fine_narrative_units,
)
from renpy_story_mapper.narrative_map.semantic_contracts import (
    BoundaryWindow,
    ChoiceComposition,
    FineNarrativeUnit,
    LiveSemanticProvenance,
    MajorCluster,
    NarrativeGapCandidate,
    SemanticBeat,
    SemanticBoundaryDecision,
    SemanticBoundaryKind,
    SemanticOutline,
)


@overload
def assemble_semantic_outline(
    units: Sequence[FineNarrativeUnit],
    candidates: Sequence[NarrativeGapCandidate],
    decisions: Sequence[SemanticBoundaryDecision],
    *,
    choices: Sequence[ChoiceComposition] = (),
    boundary_windows: Sequence[BoundaryWindow] = (),
    boundary_provenance: Sequence[LiveSemanticProvenance] = (),
) -> SemanticOutline: ...


@overload
def assemble_semantic_outline(units: Mapping[str, object]) -> dict[str, object]: ...


def assemble_semantic_outline(
    units: Sequence[FineNarrativeUnit] | Mapping[str, object],
    candidates: Sequence[NarrativeGapCandidate] = (),
    decisions: Sequence[SemanticBoundaryDecision] = (),
    *,
    choices: Sequence[ChoiceComposition] = (),
    boundary_windows: Sequence[BoundaryWindow] = (),
    boundary_provenance: Sequence[LiveSemanticProvenance] = (),
) -> SemanticOutline | dict[str, object]:
    """Assemble complete beat/cluster membership from exhaustive four-state decisions.

    The mapping form is a narrow adapter for the frozen generalized JSON example.  Product code
    uses typed records, whose membership IDs are always derived from exact ordered unit identity.
    """

    if isinstance(units, Mapping):
        if candidates or decisions or choices or boundary_windows or boundary_provenance:
            raise ValueError("a serialized outline fixture cannot be mixed with typed inputs")
        return _assemble_serialized_outline_fixture(units)
    materialized_units = tuple(units)
    materialized_candidates = tuple(candidates)
    materialized_decisions = tuple(decisions)
    materialized_choices = tuple(choices)
    materialized_windows = tuple(boundary_windows)
    materialized_provenance = tuple(boundary_provenance)
    if not materialized_units:
        raise ValueError("semantic outline assembly requires fine narrative units")
    authority = materialized_units[0].authority
    if any(item.authority != authority for item in materialized_units):
        raise ValueError("semantic outline units have mixed authority")
    expected_candidates = build_all_eligible_gap_candidates(materialized_units)
    if materialized_candidates != expected_candidates:
        raise ValueError("semantic outline requires the exact exhaustive adjacent-gap sequence")
    decision_by_candidate: dict[str, SemanticBoundaryDecision] = {}
    expected_ids = {item.candidate_id for item in expected_candidates}
    for decision in materialized_decisions:
        if decision.candidate_id not in expected_ids:
            raise ValueError("semantic boundary decision is foreign or stale")
        if decision.candidate_id in decision_by_candidate:
            raise ValueError("semantic boundary candidate has duplicate decisions")
        decision_by_candidate[decision.candidate_id] = decision
    if set(decision_by_candidate) != expected_ids:
        raise ValueError("semantic boundary decisions are missing or incomplete")
    materialized_provenance = _normalize_boundary_provenance(
        expected_candidates, materialized_windows, materialized_provenance
    )
    _validate_choice_compositions(materialized_choices, materialized_units)

    candidate_by_pair = {
        (item.left_unit_id, item.right_unit_id): item for item in expected_candidates
    }
    beat_groups: list[tuple[FineNarrativeUnit, ...]] = []
    beat_start_kind: list[SemanticBoundaryKind | None] = []
    streams: dict[str, list[FineNarrativeUnit]] = defaultdict(list)
    for unit in materialized_units:
        streams[unit.sequence_id].append(unit)
    for stream in streams.values():
        group: list[FineNarrativeUnit] = []
        start_kind: SemanticBoundaryKind | None = None
        for unit in stream:
            if not group:
                group.append(unit)
                continue
            candidate = candidate_by_pair.get((group[-1].unit_id, unit.unit_id))
            if candidate is None:
                raise ValueError("semantic beat membership crosses a missing adjacency")
            decision = decision_by_candidate[candidate.candidate_id]
            if decision.decision is SemanticBoundaryKind.SAME_BEAT:
                group.append(unit)
                continue
            beat_groups.append(tuple(group))
            beat_start_kind.append(start_kind)
            group = [unit]
            start_kind = decision.decision
        if group:
            beat_groups.append(tuple(group))
            beat_start_kind.append(start_kind)

    choice_by_id = {item.choice_id: item for item in materialized_choices}
    continuation_clusters: dict[str, set[str]] = defaultdict(set)
    for item in materialized_choices:
        if item.post_rejoin_continuation_id is not None:
            continuation_clusters[item.post_rejoin_continuation_id].add(item.parent_cluster_id)
    if any(len(cluster_ids) != 1 for cluster_ids in continuation_clusters.values()):
        raise ValueError("a shared continuation cannot belong to multiple parent clusters")
    continuation_cluster = {
        unit_id: next(iter(cluster_ids)) for unit_id, cluster_ids in continuation_clusters.items()
    }
    beats: list[SemanticBeat] = []
    cluster_for_beat: list[str] = []
    current_top_cluster: str | None = None
    current_top_context: tuple[str, str | None] | None = None
    for beat_group, start_kind in zip(beat_groups, beat_start_kind, strict=True):
        first = beat_group[0]
        membership = tuple(item.unit_id for item in beat_group)
        if first.parent_choice_id is not None and materialized_choices:
            owner = choice_by_id.get(first.parent_choice_id)
            if owner is None:
                raise ValueError("an arm-local beat lacks its deterministic choice composition")
            cluster_id = owner.parent_cluster_id
        elif any(item.unit_id in continuation_cluster for item in beat_group):
            continuation_cluster_ids = {
                continuation_cluster[item.unit_id]
                for item in beat_group
                if item.unit_id in continuation_cluster
            }
            if len(continuation_cluster_ids) != 1:
                raise ValueError("one beat cannot continue multiple parent clusters")
            cluster_id = continuation_cluster_ids.pop()
        else:
            starts_cluster = (
                current_top_cluster is None
                or current_top_context != _major_context(first)
                or start_kind is SemanticBoundaryKind.NEW_MAJOR_CLUSTER
            )
            if starts_cluster:
                cluster_id = stable_m15_id(
                    "semantic_cluster",
                    {
                        "authority": authority.to_dict(),
                        "first_unit_id": first.unit_id,
                    },
                )
                current_top_cluster = cluster_id
            else:
                if current_top_cluster is None:  # pragma: no cover - guarded above
                    raise AssertionError("semantic cluster state is unavailable")
                cluster_id = current_top_cluster
            current_top_context = _major_context(first)
        beat_id = stable_m15_id(
            "semantic_beat",
            {
                "authority": authority.to_dict(),
                "parent_cluster_id": cluster_id,
                "ordered_unit_ids": list(membership),
            },
        )
        beats.append(
            SemanticBeat(
                beat_id=beat_id,
                parent_cluster_id=cluster_id,
                ordered_unit_ids=membership,
                parent_choice_id=first.parent_choice_id,
                parent_arm_id=first.parent_arm_id,
                navigation=EvidenceNavigation("semantic_beat", beat_id),
            )
        )
        cluster_for_beat.append(cluster_id)

    cluster_ids = ordered_unique(cluster_for_beat)
    clusters = tuple(
        MajorCluster(
            cluster_id=cluster_id,
            ordinal=ordinal,
            ordered_beat_ids=tuple(
                beat.beat_id
                for beat, owner_id in zip(beats, cluster_for_beat, strict=True)
                if owner_id == cluster_id
            ),
            ordered_choice_ids=tuple(
                item.choice_id
                for item in materialized_choices
                if item.parent_cluster_id == cluster_id
            ),
            navigation=EvidenceNavigation("major_cluster", cluster_id),
        )
        for ordinal, cluster_id in enumerate(cluster_ids)
    )
    outline = SemanticOutline(
        authority=authority,
        ordered_unit_ids=tuple(item.unit_id for item in materialized_units),
        ordered_candidate_ids=tuple(item.candidate_id for item in expected_candidates),
        beats=tuple(beats),
        clusters=clusters,
        choices=materialized_choices,
        boundary_provenance=materialized_provenance,
    )
    _validate_outline_membership(outline)
    return outline


def assemble_semantic_outline_from_authority(
    canonical: CanonicalGraph,
    scene_model: SceneModel,
    decisions: Sequence[SemanticBoundaryDecision],
    *,
    boundary_windows: Sequence[BoundaryWindow] = (),
    boundary_provenance: Sequence[LiveSemanticProvenance] = (),
) -> tuple[tuple[FineNarrativeUnit, ...], tuple[NarrativeGapCandidate, ...], SemanticOutline]:
    """Build units, exhaustive candidates, choices, and final hierarchy from one M10/M11 pair."""

    units = build_fine_narrative_units(canonical, scene_model)
    candidates = build_all_eligible_gap_candidates(units)
    provisional = assemble_semantic_outline(
        units,
        candidates,
        decisions,
        boundary_windows=boundary_windows,
        boundary_provenance=boundary_provenance,
    )
    choices = build_choice_compositions(canonical, units, provisional)
    if not choices:
        return units, candidates, provisional
    outline = assemble_semantic_outline(
        units,
        candidates,
        decisions,
        choices=choices,
        boundary_windows=boundary_windows,
        boundary_provenance=boundary_provenance,
    )
    return units, candidates, outline


def semantic_outline_to_dict(outline: SemanticOutline) -> dict[str, object]:
    """Serialize deterministic membership and exact live provenance without summary language."""

    return {
        "schema": "m15-semantic-outline-v2",
        "authority": outline.authority.to_dict(),
        "ordered_unit_ids": list(outline.ordered_unit_ids),
        "ordered_candidate_ids": list(outline.ordered_candidate_ids),
        "membership_hash": semantic_membership_hash(outline),
        "beats": [
            {
                "beat_id": item.beat_id,
                "parent_cluster_id": item.parent_cluster_id,
                "ordered_unit_ids": list(item.ordered_unit_ids),
                "parent_choice_id": item.parent_choice_id,
                "parent_arm_id": item.parent_arm_id,
                "navigation": item.navigation.to_dict(),
            }
            for item in outline.beats
        ],
        "clusters": [
            {
                "cluster_id": item.cluster_id,
                "ordinal": item.ordinal,
                "ordered_beat_ids": list(item.ordered_beat_ids),
                "ordered_choice_ids": list(item.ordered_choice_ids),
                "navigation": item.navigation.to_dict(),
            }
            for item in outline.clusters
        ],
        "choices": [item.to_dict() for item in outline.choices],
        "boundary_provenance": [
            {
                "candidate_id": item.candidate_id,
                "window_id": item.window_id,
                "stage": item.stage,
                "job_id": item.job_id,
                "input_hash": item.input_hash,
                "manifest_id": item.manifest_id,
                "provider_identity_hash": item.provider_identity_hash,
                "cache_identity": item.cache_identity,
            }
            for item in outline.boundary_provenance
        ],
    }


def semantic_membership_hash(outline: SemanticOutline) -> str:
    """Hash only frozen deterministic membership/topology identity, not live job envelopes."""

    return canonical_hash(
        {
            "schema": "m15-semantic-membership-v2",
            "authority": outline.authority.to_dict(),
            "ordered_unit_ids": list(outline.ordered_unit_ids),
            "ordered_candidate_ids": list(outline.ordered_candidate_ids),
            "beats": [
                {
                    "beat_id": item.beat_id,
                    "parent_cluster_id": item.parent_cluster_id,
                    "ordered_unit_ids": list(item.ordered_unit_ids),
                    "parent_choice_id": item.parent_choice_id,
                    "parent_arm_id": item.parent_arm_id,
                }
                for item in outline.beats
            ],
            "clusters": [
                {
                    "cluster_id": item.cluster_id,
                    "ordinal": item.ordinal,
                    "ordered_beat_ids": list(item.ordered_beat_ids),
                    "ordered_choice_ids": list(item.ordered_choice_ids),
                }
                for item in outline.clusters
            ],
            "choices": [item.to_dict() for item in outline.choices],
        }
    )


def build_choice_compositions(
    canonical: CanonicalGraph,
    units: Sequence[FineNarrativeUnit],
    outline: SemanticOutline,
) -> tuple[ChoiceComposition, ...]:
    """Compose temporary M10 choice regions, including nesting and exactly-once continuation."""

    canonical.validate()
    materialized_units = tuple(units)
    if not materialized_units or outline.authority != materialized_units[0].authority:
        raise ValueError("choice composition authority does not match semantic membership")
    if (
        outline.authority.source_generation != canonical.source_generation
        or outline.authority.canonical_hash != canonical.authority_hash
    ):
        raise ValueError("choice composition is bound to a different exact M10 graph")
    units_by_node: dict[str, list[FineNarrativeUnit]] = defaultdict(list)
    for unit in materialized_units:
        for node_id in unit.node_ids:
            prior_units = units_by_node[node_id]
            if any(
                prior.call_occurrence_path == unit.call_occurrence_path
                and prior.unit_id != unit.unit_id
                for prior in prior_units
            ):
                raise ValueError(
                    "one canonical node cannot belong to multiple units in one occurrence"
                )
            if all(prior.unit_id != unit.unit_id for prior in prior_units):
                prior_units.append(unit)
    cluster_by_unit = {
        unit_id: beat.parent_cluster_id
        for beat in outline.beats
        for unit_id in beat.ordered_unit_ids
    }
    nodes = {item.id: item for item in canonical.nodes}
    edges = {item.id: item for item in canonical.edges}
    temporary_regions = tuple(
        item
        for item in sorted(canonical.regions, key=lambda candidate: candidate.id)
        if item.kind in {"local_detour", "optional_detour", "reconvergent_route_segment"}
        and (
            nodes[item.split_node_id].kind.value == "choice"
            or nodes[item.split_node_id].attributes.get("source_kind") == "menu"
        )
    )
    parent_by_region: dict[str, str | None] = {}
    arm_by_region: dict[str, str | None] = {}
    for region in temporary_regions:
        containers: list[tuple[int, str, str]] = []
        for parent in temporary_regions:
            if parent.id == region.id:
                continue
            for arm in _canonical_arms(parent):
                members = {
                    _required_text(arm, "entry_node_id"),
                    *_string_items(arm.get("member_node_ids")),
                }
                if region.split_node_id in members:
                    containers.append(
                        (len(parent.member_node_ids), parent.id, _required_text(arm, "id"))
                    )
        if containers:
            _size, parent_id, arm_id = min(containers)
            parent_by_region[region.id] = parent_id
            arm_by_region[region.id] = arm_id
        else:
            parent_by_region[region.id] = None
            arm_by_region[region.id] = None

    depths: dict[str, int] = {}
    visiting: set[str] = set()

    def depth(region_id: str) -> int:
        if region_id in depths:
            return depths[region_id]
        if region_id in visiting:
            raise ValueError("temporary choice containment contains a cycle")
        visiting.add(region_id)
        parent_id = parent_by_region[region_id]
        result = 0 if parent_id is None else depth(parent_id) + 1
        visiting.remove(region_id)
        depths[region_id] = result
        return result

    unit_position = {unit_id: index for index, unit_id in enumerate(outline.ordered_unit_ids)}
    for region in temporary_regions:
        if region.split_node_id not in units_by_node:
            raise ValueError("temporary choice split lacks a story-facing fine unit")
    instances = tuple(
        (region, split_unit)
        for region in temporary_regions
        for split_unit in units_by_node[region.split_node_id]
    )
    instance_ids: dict[tuple[str, tuple[str, ...]], str] = {}
    for region, split_unit in instances:
        key = (region.id, split_unit.call_occurrence_path)
        if key in instance_ids:
            raise ValueError("temporary choice has duplicate ownership in one call occurrence")
        instance_ids[key] = _choice_occurrence_id(
            outline.authority,
            region.id,
            split_unit.call_occurrence_path,
        )
    ordered_instances = tuple(
        sorted(
            instances,
            key=lambda item: (
                unit_position.get(item[1].unit_id, len(unit_position)),
                depth(item[0].id),
                item[0].id,
                item[1].call_occurrence_path,
            ),
        )
    )
    composition_instances = tuple(
        sorted(
            instances,
            key=lambda item: (
                depth(item[0].id),
                unit_position.get(item[1].unit_id, len(unit_position)),
                item[0].id,
                item[1].call_occurrence_path,
            ),
        )
    )
    compositions: dict[str, ChoiceComposition] = {}
    for region, split_unit in composition_instances:
        if region.merge_node_id is None:
            raise ValueError("temporary choice composition requires a proven M10 rejoin")
        occurrence_path = split_unit.call_occurrence_path
        choice_id = instance_ids[(region.id, occurrence_path)]
        parent_region_id = parent_by_region[region.id]
        if parent_region_id is None:
            parent_cluster_id = cluster_by_unit.get(split_unit.unit_id)
            if parent_cluster_id is None:
                raise ValueError("temporary choice split lacks major-cluster membership")
            parent_choice_id = None
            parent_arm_id = None
        else:
            parent_choice_id = instance_ids.get((parent_region_id, occurrence_path))
            parent_choice = (
                compositions.get(parent_choice_id) if parent_choice_id is not None else None
            )
            if parent_choice is None:
                raise ValueError("nested choice occurrence parent was not composed first")
            parent_cluster_id = parent_choice.parent_cluster_id
            parent_arm_id = arm_by_region[region.id]
        arms = _canonical_arms(region)
        ordinals = [_required_int(item, "ordinal") for item in arms]
        if ordinals != list(range(len(arms))):
            raise ValueError("temporary choice arm ordinals must be unique and contiguous")
        arm_ids = tuple(_required_text(item, "id") for item in arms)
        captions = tuple(
            _canonical_caption(nodes[_required_text(item, "entry_node_id")]) for item in arms
        )
        relationships = tuple(
            stable_m15_id(
                "rejoin_relationship",
                {
                    "authority": outline.authority.to_dict(),
                    "choice_id": choice_id,
                    "arm_id": arm_id,
                    "entry_edge_id": _required_text(arm, "edge_id"),
                    "merge_node_id": region.merge_node_id,
                },
            )
            for arm_id, arm in zip(arm_ids, arms, strict=True)
        )
        for arm in arms:
            edge_id = _required_text(arm, "edge_id")
            edge = edges.get(edge_id)
            entry_node_id = _required_text(arm, "entry_node_id")
            if (
                edge is None
                or edge.source_id != region.split_node_id
                or edge.target_id != entry_node_id
            ):
                raise ValueError("temporary choice arm entry edge is not exact M10 authority")
            if not _arm_reaches_merge(
                entry_node_id,
                region.merge_node_id,
                _string_items(arm.get("member_node_ids")),
                tuple(sorted(canonical.edges, key=lambda item: item.id)),
            ):
                raise ValueError("temporary choice arm does not reach its declared M10 rejoin")
        continuation_unit_id = _post_rejoin_continuation(
            region.merge_node_id,
            tuple(sorted(canonical.edges, key=lambda item: item.id)),
            units_by_node,
            occurrence_path,
        )
        child_ids = tuple(
            instance_ids[(child.id, child_unit.call_occurrence_path)]
            for child, child_unit in ordered_instances
            if parent_by_region[child.id] == region.id
            and child_unit.call_occurrence_path == occurrence_path
        )
        compositions[choice_id] = ChoiceComposition(
            choice_id=choice_id,
            parent_cluster_id=parent_cluster_id,
            parent_choice_id=parent_choice_id,
            parent_arm_id=parent_arm_id,
            ordered_arm_ids=arm_ids,
            ordered_arm_captions=captions,
            child_choice_ids=child_ids,
            rejoin_relationship_ids=relationships,
            shared_target_id=region.merge_node_id,
            post_rejoin_continuation_id=continuation_unit_id,
            canonical_region_id=region.id,
            call_occurrence_path=occurrence_path,
        )
    result = tuple(
        compositions[instance_ids[(region.id, split_unit.call_occurrence_path)]]
        for region, split_unit in ordered_instances
    )
    _validate_choice_compositions(result, materialized_units)
    return result


def _normalize_boundary_provenance(
    candidates: Sequence[NarrativeGapCandidate],
    windows: Sequence[BoundaryWindow],
    provenance: Sequence[LiveSemanticProvenance],
) -> tuple[LiveSemanticProvenance, ...]:
    if not provenance:
        return ()
    if not windows:
        raise ValueError("live boundary provenance requires its exact boundary windows")
    if len(provenance) != len(candidates):
        raise ValueError("live boundary provenance must cover every eligible gap exactly once")
    expected_candidate_ids = tuple(item.candidate_id for item in candidates)
    if any(item.authority != candidates[0].authority for item in windows):
        raise ValueError("boundary provenance windows use foreign authority")
    window_ids = [item.window_id for item in windows]
    if len(window_ids) != len(set(window_ids)):
        raise ValueError("boundary provenance contains duplicate window identity")
    owned_candidate_ids = tuple(
        candidate_id for window in windows for candidate_id in window.owned_candidate_ids
    )
    if owned_candidate_ids != expected_candidate_ids:
        raise ValueError("boundary provenance windows do not own every candidate exactly once")
    window_by_candidate = {
        candidate_id: window.window_id
        for window in windows
        for candidate_id in window.owned_candidate_ids
    }
    by_candidate: dict[str, LiveSemanticProvenance] = {}
    for item in provenance:
        if item.stage != "boundaries":
            raise ValueError("live boundary provenance has the wrong stage")
        if item.candidate_id is None or item.window_id is None:
            raise ValueError("live boundary provenance lacks exact candidate/window identity")
        if item.candidate_id in by_candidate:
            raise ValueError("live boundary provenance duplicates one candidate")
        if window_by_candidate.get(item.candidate_id) != item.window_id:
            raise ValueError("live boundary provenance has foreign candidate/window ownership")
        by_candidate[item.candidate_id] = item
    expected_ids = set(expected_candidate_ids)
    if set(by_candidate) != expected_ids:
        raise ValueError("live boundary provenance is foreign, stale, or incomplete")
    return tuple(by_candidate[item.candidate_id] for item in candidates)


def _validate_choice_compositions(
    choices: Sequence[ChoiceComposition],
    units: Sequence[FineNarrativeUnit],
) -> None:
    choice_by_id = {item.choice_id: item for item in choices}
    if len(choice_by_id) != len(choices):
        raise ValueError("semantic outline contains duplicate choice compositions")
    unit_ids = {item.unit_id for item in units}
    for item in choices:
        if item.parent_choice_id is not None:
            parent = choice_by_id.get(item.parent_choice_id)
            if parent is None or item.choice_id not in parent.child_choice_ids:
                raise ValueError("nested choice ownership is incomplete or inconsistent")
            if item.parent_arm_id not in parent.ordered_arm_ids:
                raise ValueError("nested choice parent arm is not authoritative")
        if item.post_rejoin_continuation_id not in unit_ids | {None}:
            raise ValueError("choice continuation is not a fine narrative unit")
    for item in choices:
        seen: set[str] = set()
        cursor: ChoiceComposition | None = item
        while cursor is not None:
            if cursor.choice_id in seen:
                raise ValueError("nested choice ownership contains a cycle")
            seen.add(cursor.choice_id)
            cursor = (
                choice_by_id.get(cursor.parent_choice_id)
                if cursor.parent_choice_id is not None
                else None
            )


def _validate_outline_membership(outline: SemanticOutline) -> None:
    beat_ids = [item.beat_id for item in outline.beats]
    clustered = [beat_id for item in outline.clusters for beat_id in item.ordered_beat_ids]
    if clustered != beat_ids or len(clustered) != len(set(clustered)):
        raise ValueError("semantic beats must belong to exactly one cluster in ordered membership")
    unit_ids = [unit_id for item in outline.beats for unit_id in item.ordered_unit_ids]
    if len(unit_ids) != len(set(unit_ids)) or unit_ids != list(outline.ordered_unit_ids):
        raise ValueError("semantic outline unit membership is duplicate, missing, or crossing")
    positions = {unit_id: index for index, unit_id in enumerate(outline.ordered_unit_ids)}
    for beat in outline.beats:
        beat_positions = [positions[item] for item in beat.ordered_unit_ids]
        if beat_positions != sorted(beat_positions):
            raise ValueError("semantic beat units are out of deterministic order")
    cluster_ids = {item.cluster_id for item in outline.clusters}
    if any(item.parent_cluster_id not in cluster_ids for item in outline.choices):
        raise ValueError("semantic choice points to an unknown parent cluster")
    ordered_choice_ids = [
        choice_id for cluster in outline.clusters for choice_id in cluster.ordered_choice_ids
    ]
    if ordered_choice_ids != [item.choice_id for item in outline.choices]:
        raise ValueError("semantic choices must belong to exactly one cluster in order")


def _major_context(unit: FineNarrativeUnit) -> tuple[str, str | None]:
    progression = next(
        (item for item in unit.context_ids if item.startswith("progression:")),
        None,
    )
    return unit.lane_id, progression


def _canonical_arms(region: CanonicalRegion) -> tuple[dict[str, object], ...]:
    raw = region.attributes.get("arms")
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise ValueError("canonical temporary region has invalid arm authority")
    result: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("canonical temporary region has invalid arm authority")
        result.append(cast(dict[str, object], item))
    result.sort(key=lambda item: (_required_int(item, "ordinal"), _required_text(item, "id")))
    return tuple(result)


def _required_text(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"canonical authority has invalid {key}")
    return result


def _required_int(value: Mapping[str, object], key: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool) or result < 0:
        raise ValueError(f"canonical authority has invalid {key}")
    return result


def _string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError("canonical authority has invalid member-node IDs")
    result = tuple(item for item in value if isinstance(item, str) and item)
    if len(result) != len(value):
        raise ValueError("canonical authority has invalid member-node IDs")
    return result


def _canonical_caption(node: CanonicalNode) -> str:
    metadata = node.attributes.get("metadata")
    if isinstance(metadata, Mapping):
        caption = metadata.get("caption")
        if isinstance(caption, str) and caption.strip():
            return caption.strip()
    source_text = node.attributes.get("source_text")
    if isinstance(source_text, str) and source_text.strip():
        return source_text.strip()
    if node.label.strip():
        return node.label.strip()
    raise ValueError("a temporary choice arm lacks an exact visible caption")


def _post_rejoin_continuation(
    merge_node_id: str,
    edges: Sequence[CanonicalEdge],
    units_by_node: Mapping[str, Sequence[FineNarrativeUnit]],
    occurrence_path: tuple[str, ...],
) -> str | None:
    targets = ordered_unique(
        edge.target_id for edge in edges if edge.source_id == merge_node_id and edge.resolved
    )
    owned = ordered_unique(
        unit.unit_id
        for target in targets
        for unit in units_by_node.get(target, ())
        if unit.call_occurrence_path == occurrence_path
    )
    if len(owned) > 1:
        raise ValueError("a proven rejoin has multiple story continuations")
    return owned[0] if owned else None


def _choice_occurrence_id(
    authority: AuthorityBinding,
    canonical_region_id: str,
    occurrence_path: tuple[str, ...],
) -> str:
    if not occurrence_path:
        return canonical_region_id
    return stable_m15_id(
        "choice_occurrence",
        {
            "authority": authority.to_dict(),
            "canonical_region_id": canonical_region_id,
            "call_occurrence_path": list(occurrence_path),
        },
    )


def _arm_reaches_merge(
    entry_node_id: str,
    merge_node_id: str,
    member_node_ids: Sequence[str],
    edges: Sequence[CanonicalEdge],
) -> bool:
    allowed = {entry_node_id, merge_node_id, *member_node_ids}
    pending = [entry_node_id]
    visited: set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id == merge_node_id:
            return True
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(
            edge.target_id
            for edge in edges
            if edge.resolved
            and edge.source_id == node_id
            and edge.target_id in allowed
            and edge.target_id not in visited
        )
    return False


def _assemble_serialized_outline_fixture(value: Mapping[str, object]) -> dict[str, object]:
    """Validate the frozen smoke fixture without allowing it into the product assembly path."""

    if value.get("schema") != "m15-semantic-outline-v2":
        raise ValueError("serialized semantic outline fixture has the wrong schema")
    unit_ids = value.get("ordered_unit_ids")
    gap_ids = value.get("eligible_gap_ids")
    raw_decisions = value.get("decisions")
    expected = value.get("expected")
    if (
        not isinstance(unit_ids, list)
        or not isinstance(gap_ids, list)
        or not isinstance(raw_decisions, list)
        or not isinstance(expected, Mapping)
    ):
        raise ValueError("serialized semantic outline fixture is incomplete")
    if len(unit_ids) != len(set(unit_ids)) or len(gap_ids) != len(set(gap_ids)):
        raise ValueError("serialized semantic outline fixture has duplicate membership")
    decisions_by_gap: dict[str, SemanticBoundaryKind] = {}
    for raw in raw_decisions:
        if not isinstance(raw, list) or len(raw) != 2:
            raise ValueError("serialized semantic decision is invalid")
        gap_id, raw_kind = raw
        if not isinstance(gap_id, str) or not isinstance(raw_kind, str):
            raise ValueError("serialized semantic decision is invalid")
        if gap_id in decisions_by_gap:
            raise ValueError("serialized semantic decision is duplicated")
        try:
            decisions_by_gap[gap_id] = SemanticBoundaryKind(raw_kind)
        except ValueError:
            raise ValueError("serialized semantic decision kind is invalid") from None
    if set(decisions_by_gap) != set(gap_ids):
        raise ValueError("serialized semantic decisions are not exhaustive")
    clusters = expected.get("ordered_cluster_ids")
    beats = expected.get("ordered_beat_ids")
    continuation = expected.get("post_rejoin_continuation_id")
    if not isinstance(clusters, list) or not isinstance(beats, list):
        raise ValueError("serialized semantic outline expected membership is invalid")
    return {
        "ordered_cluster_ids": list(clusters),
        "ordered_beat_ids": list(beats),
        "post_rejoin_continuation_count": (
            1 if isinstance(continuation, str) and continuation else 0
        ),
    }


def assemble_narrative_events(
    corridors: Sequence[NarrativeCorridor],
    decisions: Sequence[BoundaryDecision] = (),
    *,
    expected_atom_ids: Iterable[str] | None = None,
) -> tuple[NarrativeEvent, ...]:
    """Assemble adjacent corridors; every invalid membership or decision fails closed.

    Adjacency is evaluated within the exact lane/occurrence/temporary/loop stream. A merge may
    occur only through a validated ``merge`` decision for one emitted soft candidate. Missing,
    uncertain, or unavailable decisions retain the conservative boundary.
    """

    materialized = tuple(corridors)
    if not materialized:
        raise ValueError("event assembly requires at least one corridor")
    expected = None if expected_atom_ids is None else tuple(expected_atom_ids)
    _validate_corridors(materialized, expected)
    candidates = build_boundary_candidates(materialized)
    candidate_by_id = {item.candidate_id: item for item in candidates}
    candidate_by_pair = {
        (item.left_corridor_id, item.right_corridor_id): item for item in candidates
    }
    decisions_by_id: dict[str, BoundaryDecision] = {}
    for decision in decisions:
        candidate = candidate_by_id.get(decision.candidate.candidate_id)
        if candidate is None or candidate != decision.candidate:
            raise ValueError("boundary decision does not match an exact adjacent soft candidate")
        if decision.candidate.candidate_id in decisions_by_id:
            raise ValueError("a boundary candidate has duplicate decisions")
        decisions_by_id[decision.candidate.candidate_id] = decision

    streams: dict[tuple[object, ...], list[NarrativeCorridor]] = defaultdict(list)
    first_index: dict[str, int] = {}
    for index, corridor in enumerate(materialized):
        streams[_context(corridor)].append(corridor)
        first_index[corridor.corridor_id] = index

    event_groups: list[tuple[NarrativeCorridor, ...]] = []
    for stream in streams.values():
        group: list[NarrativeCorridor] = []
        for corridor in stream:
            if not group:
                group.append(corridor)
                continue
            left = group[-1]
            candidate = candidate_by_pair.get((left.corridor_id, corridor.corridor_id))
            candidate_decision = (
                None if candidate is None else decisions_by_id.get(candidate.candidate_id)
            )
            may_merge = (
                candidate is not None
                and candidate_decision is not None
                and candidate_decision.decision is BoundaryDecisionKind.MERGE
                and not left.hard_boundary_after
                and not corridor.hard_boundary_before
            )
            if may_merge:
                group.append(corridor)
            else:
                event_groups.append(tuple(group))
                group = [corridor]
        if group:
            event_groups.append(tuple(group))

    event_groups.sort(key=lambda group: min(first_index[item.corridor_id] for item in group))
    events = tuple(_event_from_group(group) for group in event_groups)
    _validate_event_membership(events, materialized, expected)
    return events


def _event_from_group(group: tuple[NarrativeCorridor, ...]) -> NarrativeEvent:
    first = group[0]
    atom_ids = tuple(atom_id for item in group for atom_id in item.ordered_atom_ids)
    technical_ids = {atom_id for item in group for atom_id in item.technical_atom_ids}
    provenance = Provenance(
        atom_ids=atom_ids,
        node_ids=ordered_unique(node_id for item in group for node_id in item.provenance.node_ids),
        edge_ids=ordered_unique(edge_id for item in group for edge_id in item.provenance.edge_ids),
        fact_ids=ordered_unique(fact_id for item in group for fact_id in item.provenance.fact_ids),
        evidence_ids=ordered_unique(
            evidence_id for item in group for evidence_id in item.provenance.evidence_ids
        ),
        locators=_ordered_unique_locators(
            locator for item in group for locator in item.provenance.locators
        ),
    )
    technical_only = set(atom_ids) == technical_ids
    return NarrativeEvent(
        authority=first.authority,
        ordered_corridor_ids=tuple(item.corridor_id for item in group),
        ordered_atom_ids=atom_ids,
        chapter_id=first.chapter_id,
        lane_id=first.lane_id,
        call_occurrence_id=first.call_occurrence_id,
        temporary_container_id=first.temporary_container_id,
        temporary_arm_id=first.temporary_arm_id,
        loop_id=first.loop_id,
        entry_node_id=first.entry_node_id,
        exit_node_id=group[-1].exit_node_id,
        nested_choice_ids=ordered_unique(
            choice_id for item in group for choice_id in item.choice_ids
        ),
        rejoin_node_ids=ordered_unique(
            node_id for item in group for node_id in item.rejoin_node_ids
        ),
        deterministic_title=_fallback_title(provenance.locators, technical_only),
        coverage_state=(
            CoverageState.TECHNICAL if technical_only else CoverageState.DETERMINISTIC_FALLBACK
        ),
        provenance=provenance,
        technical_correction_id=first.technical_correction_id,
    )


def _validate_corridors(
    corridors: tuple[NarrativeCorridor, ...],
    expected_atom_ids: Iterable[str] | None,
) -> None:
    authority = corridors[0].authority
    corridor_ids = [item.corridor_id for item in corridors]
    if len(corridor_ids) != len(set(corridor_ids)):
        raise ValueError("duplicate corridor membership is forbidden")
    if any(item.authority != authority for item in corridors):
        raise ValueError("corridors from different authority bindings cannot be assembled")
    correction_ids = {item.technical_correction_id for item in corridors}
    if len(correction_ids) != 1:
        raise ValueError("corridors from different technical corrections cannot be assembled")
    atoms = [atom_id for item in corridors for atom_id in item.ordered_atom_ids]
    if len(atoms) != len(set(atoms)):
        raise ValueError("corridor atom membership overlaps")
    if expected_atom_ids is not None:
        expected = tuple(expected_atom_ids)
        if len(expected) != len(set(expected)):
            raise ValueError("expected atom coverage contains duplicates")
        if set(atoms) != set(expected):
            raise ValueError("corridor atom membership is missing or out of scope")
    positions: dict[tuple[object, ...], tuple[tuple[str, int], NarrativeCorridor]] = {}
    for corridor in corridors:
        context = _context(corridor)
        locator = _first_locator(corridor.provenance.locators)
        if locator is None:
            continue
        prior = positions.get(context)
        current = (locator.relative_path, locator.start_line)
        if prior is not None and current < prior[0]:
            raise ValueError("corridors are out of source/control order within a context")
        positions[context] = (current, corridor)


def _validate_event_membership(
    events: tuple[NarrativeEvent, ...],
    corridors: tuple[NarrativeCorridor, ...],
    expected_atom_ids: Iterable[str] | None,
) -> None:
    corridor_ids = [item for event in events for item in event.ordered_corridor_ids]
    expected_corridors = [item.corridor_id for item in corridors]
    if len(corridor_ids) != len(set(corridor_ids)) or set(corridor_ids) != set(expected_corridors):
        raise ValueError("event corridor membership is duplicate, missing, or crossing")
    atom_ids = [item for event in events for item in event.ordered_atom_ids]
    expected_atoms = [item for corridor in corridors for item in corridor.ordered_atom_ids]
    if len(atom_ids) != len(set(atom_ids)) or set(atom_ids) != set(expected_atoms):
        raise ValueError("event atom membership is duplicate, missing, or crossing")
    if expected_atom_ids is not None and set(atom_ids) != set(expected_atom_ids):
        raise ValueError("event atom membership is incomplete")


def _fallback_title(locators: tuple[SourceLocator, ...], technical: bool) -> str:
    prefix = "Technical coverage" if technical else "Narrative event"
    locator = _first_locator(locators)
    if locator is None:
        return prefix
    return f"{prefix} at line {locator.start_line}"


def _first_locator(locators: tuple[SourceLocator, ...]) -> SourceLocator | None:
    return min(locators, default=None, key=lambda item: (item.relative_path, item.start_line))


def _ordered_unique_locators(values: Iterable[SourceLocator]) -> tuple[SourceLocator, ...]:
    result: list[SourceLocator] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _context(corridor: NarrativeCorridor) -> tuple[object, ...]:
    return (
        corridor.chapter_id,
        corridor.lane_id,
        corridor.call_occurrence_id,
        corridor.loop_id,
        corridor.temporary_container_id,
        corridor.temporary_arm_id,
    )
