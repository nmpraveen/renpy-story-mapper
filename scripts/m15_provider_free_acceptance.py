"""Provider-free M15 synthetic and opt-in exact MsDay1 acceptance.

This runner opens the comparison project through SQLite read-only/immutable mode. It never reads
story text into its report, invokes Ren'Py/game code, or writes beside the private fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from renpy_story_mapper.canonical_graph_contract import (
    CANONICAL_GRAPH_SCHEMA,
    CanonicalEdge,
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeKind,
    CanonicalRegion,
    DerivedProof,
    OriginReference,
    ReachabilityStatus,
    SourceEvidence,
)
from renpy_story_mapper.m11_scene_model import (
    M11_ATOM_RULE_VERSION,
    M11_BOUNDARY_RULE_VERSION,
    AtomKind,
    BoundaryDecision,
    BoundaryStrength,
    CanonicalBinding,
    CanonicalCoverage,
    Chapter,
    CoverageCollection,
    CoverageDisposition,
    CoverageEntry,
    DecisionStatus,
    LaneKind,
    PersistentLane,
    Scene,
    SceneModel,
    SceneRepeatability,
    StoryAtom,
)
from renpy_story_mapper.m11_scene_model import (
    Provenance as M11Provenance,
)
from renpy_story_mapper.m11_scene_projection import scene_model_from_stored_results
from renpy_story_mapper.m12_service import canonical_graph_from_mapping
from renpy_story_mapper.narrative_map import (
    NarrativeCorridor,
    NarrativeEvent,
    NarrativeMap,
    NarrativeMapNode,
    assemble_narrative_events,
    build_narrative_corridors,
    build_narrative_map,
)
from renpy_story_mapper.narrative_map.contracts import NarrativeNodeKind
from renpy_story_mapper.narrative_map.coverage_corrections import (
    M15_LEADING_TECHNICAL_CORRECTION_KEY,
    M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION,
    decode_leading_technical_correction_envelope,
)

EXPECTED_SOURCE_HASH = "14aa44ed95dec5402dfb02a1c4e01e63b3f3e329cf04fec37b04edebb5d588a6"
EXPECTED_MENU_LINES = (143, 191, 623, 674)
EXPECTED_MAJOR_STARTS = (52, 280, 334, 431)
EXPECTED_MAJOR_ORDER = ("prologue", "terrance", "janet", "dinner", "faye")
EXPECTED_MAJOR_MEMBERSHIP_BOUNDS = (
    ("prologue", (27, 50)),
    ("terrance", (52, 278)),
    ("janet", (280, 332)),
    ("dinner", (334, 430)),
    ("faye", (431, 789)),
)
EXPECTED_SETUP_END_LINE = 26
EXPECTED_PROLOGUE_START_RANGE = (27, 51)
BLOCKED_TITLES = {"start", "clean", "module ending", "technical merge"}

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type NodeSpec = tuple[str, AtomKind, CanonicalNodeKind, str, str, dict[str, object]]
type EdgeSpec = tuple[str, str, str, str, bool, dict[str, object]]
type RegionSpec = tuple[str, str, str, str | None, tuple[str, ...], dict[str, object]]


def evaluate_exact_msday1(
    fixture_root: Path,
    project_path: Path,
    comparison_project_path: Path | None = None,
) -> dict[str, JsonValue]:
    """Evaluate exact private Day 1 authority without emitting or modifying story content."""

    fixture_root, project_path = _resolve_private_paths(fixture_root, project_path)
    source = fixture_root / "input" / "game" / "v0.01_clean.rpy"
    if not source.is_file() or not project_path.is_file():
        raise FileNotFoundError("the opt-in MsDay1 source and comparison project are required")
    before_source = _fingerprint(source)
    before_project = _fingerprint(project_path)
    comparison_project = (
        None if comparison_project_path is None else comparison_project_path.resolve()
    )
    if comparison_project is not None and comparison_project == project_path.resolve():
        raise ValueError("the seeded working project must differ from the comparison project")
    before_comparison = None if comparison_project is None else _fingerprint(comparison_project)
    if before_source[0] != EXPECTED_SOURCE_HASH:
        raise ValueError("the private source hash does not match the frozen M15 fixture")
    if len(source.read_bytes().splitlines()) != 793:
        raise ValueError("the exact private scope must contain 793 reconstructed lines")

    canonical_value, phase_results, correction_value = _read_authority(project_path)
    canonical = canonical_graph_from_mapping(canonical_value)
    model = scene_model_from_stored_results(phase_results)
    correction = (
        None
        if correction_value is None
        else decode_leading_technical_correction_envelope(correction_value)
    )
    corridors = build_narrative_corridors(
        canonical,
        model,
        technical_correction=correction,
    )
    events = assemble_narrative_events(
        corridors,
        expected_atom_ids=(item.id for item in model.atoms),
    )
    narrative_map = build_narrative_map(canonical, events, corridors=corridors)

    branch_pairs = _canonical_choice_pairs(canonical, model)
    expected_pairs = {143: 165, 191: 233, 623: 793, 674: 793}
    if branch_pairs != expected_pairs:
        raise ValueError("the exact narrative choice/rejoin anchors changed")
    observations = _exact_product_observations(
        canonical,
        model,
        corridors,
        events,
        narrative_map,
        branch_pairs,
    )

    blocked = sorted(
        {
            node.title
            for node in narrative_map.nodes
            if node.kind is not NarrativeNodeKind.TECHNICAL_COVERAGE
            and node.title.casefold() in BLOCKED_TITLES
        }
    )
    map_cluster_count = len(observations.cluster_starts)
    if map_cluster_count != len(EXPECTED_MAJOR_ORDER):
        raise ValueError("the provider-free map does not expose exactly five major clusters")
    if blocked:
        raise ValueError("the provider-free map exposes a blocked technical title")

    after_source = _fingerprint(source)
    after_project = _fingerprint(project_path)
    after_comparison = None if comparison_project is None else _fingerprint(comparison_project)
    if (
        before_source != after_source
        or before_project != after_project
        or before_comparison != after_comparison
    ):
        raise RuntimeError("read-only acceptance changed a private input")
    return {
        "schema": "m15-provider-free-exact-report-v1",
        "source_sha256": before_source[0],
        "source_size": before_source[1],
        "source_mtime_ns": before_source[2],
        "project_sha256": before_project[0],
        "project_size": before_project[1],
        "project_mtime_ns": before_project[2],
        "comparison_project_sha256": (None if before_comparison is None else before_comparison[0]),
        "comparison_project_size": (None if before_comparison is None else before_comparison[1]),
        "comparison_project_mtime_ns": (
            None if before_comparison is None else before_comparison[2]
        ),
        "technical_correction_id": (None if correction is None else correction.correction_id),
        "technical_correction_hash": (None if correction is None else correction.normalized_hash),
        "canonical_hash": canonical.authority_hash,
        "atom_hash": model.structural_hash,
        "corridor_count": len(corridors),
        "event_count": len(events),
        "map_node_count": len(narrative_map.nodes),
        "map_edge_count": len(narrative_map.edges),
        "major_cluster_count": map_cluster_count,
        "terrance_choice_rejoins": cast(
            JsonValue,
            [[line, branch_pairs[line]] for line in EXPECTED_MENU_LINES[:2]],
        ),
        "faye_choice_rejoins": cast(
            JsonValue,
            [[line, branch_pairs[line]] for line in EXPECTED_MENU_LINES[2:]],
        ),
        "terrance_event_end_line": observations.cluster_bounds[1][1],
        "janet_event_start_line": observations.cluster_bounds[2][0],
        "technical_setup_end_line": observations.cluster_starts[0] - 1,
        "prologue_event_start_line": observations.cluster_starts[0],
        "day1_event_start_line": observations.cluster_starts[1],
        "major_event_order": cast(JsonValue, list(observations.cluster_labels)),
        "blocked_technical_titles": cast(JsonValue, blocked),
        "provider_calls": 0,
        "game_execution_count": 0,
        "source_unchanged": True,
        "project_unchanged": True,
        "comparison_project_unchanged": True,
    }


class _ExactObservations:
    def __init__(
        self,
        cluster_starts: tuple[int, ...],
        cluster_bounds: tuple[tuple[int, int], ...],
        cluster_labels: tuple[str, ...],
    ) -> None:
        self.cluster_starts = cluster_starts
        self.cluster_bounds = cluster_bounds
        self.cluster_labels = cluster_labels


def _exact_product_observations(
    canonical: CanonicalGraph,
    model: SceneModel,
    corridors: tuple[NarrativeCorridor, ...],
    events: tuple[NarrativeEvent, ...],
    narrative_map: NarrativeMap,
    branch_pairs: Mapping[int, int],
) -> _ExactObservations:
    """Derive exact gates only from assembled membership and visible presentation output."""

    corridor_by_id = {item.corridor_id: item for item in corridors}
    atom_by_id = {item.id: item for item in model.atoms}
    event_by_id = {item.event_id: item for item in events}
    for event in events:
        owned_atoms = tuple(
            atom_id
            for corridor_id in event.ordered_corridor_ids
            for atom_id in corridor_by_id[corridor_id].ordered_atom_ids
        )
        if (
            event.ordered_atom_ids != owned_atoms
            or event.provenance.atom_ids != owned_atoms
            or any(atom_id not in atom_by_id for atom_id in owned_atoms)
        ):
            raise ValueError("exact event atom ownership does not match assembled corridors")
    if narrative_map.event_ids != tuple(item.event_id for item in events):
        raise ValueError("exact map event membership does not match assembled events")
    if [item.ordinal for item in narrative_map.nodes] != list(range(len(narrative_map.nodes))):
        raise ValueError("exact visible map order is not the presentation order")

    base_kinds = {
        NarrativeNodeKind.EVENT_CLUSTER,
        NarrativeNodeKind.SUB_EVENT,
        NarrativeNodeKind.CHOICE_ARM,
        NarrativeNodeKind.CONTINUATION,
        NarrativeNodeKind.TERMINAL,
        NarrativeNodeKind.UNRESOLVED,
        NarrativeNodeKind.TECHNICAL_COVERAGE,
    }
    base_by_event: dict[str, NarrativeMapNode] = {}
    node_by_id = {item.node_id: item for item in narrative_map.nodes}
    for node in narrative_map.nodes:
        technical_auxiliary = (
            node.kind is NarrativeNodeKind.TECHNICAL_COVERAGE
            and node.navigation.target_kind in {"canonical_region", "canonical_node"}
        )
        if node.event_id in event_by_id and node.kind in base_kinds and not technical_auxiliary:
            if node.event_id is None:
                raise ValueError("exact presentation event identity is missing")
            if node.event_id in base_by_event:
                raise ValueError("exact presentation exposes duplicate event nodes")
            base_by_event[node.event_id] = node
    if set(base_by_event) != set(event_by_id):
        raise ValueError("exact presentation is missing assembled event nodes")

    cluster_nodes = tuple(
        item for item in narrative_map.nodes if item.kind is NarrativeNodeKind.EVENT_CLUSTER
    )
    event_ids_by_cluster: dict[str, set[str]] = {item.node_id: set() for item in cluster_nodes}
    for event_id, event_node in base_by_event.items():
        current_node: NarrativeMapNode | None = event_node
        visited: set[str] = set()
        while current_node is not None and current_node.kind is not NarrativeNodeKind.EVENT_CLUSTER:
            if current_node.node_id in visited:
                raise ValueError("exact presentation parentage contains a cycle")
            visited.add(current_node.node_id)
            current_node = (
                None
                if current_node.parent_node_id is None
                else node_by_id.get(current_node.parent_node_id)
            )
        if current_node is not None:
            event_ids_by_cluster[current_node.node_id].add(event_id)

    cluster_bounds: list[tuple[int, int]] = []
    for cluster in cluster_nodes:
        story_lines = [
            atom_by_id[atom_id].source_order[1]
            for event_id in event_ids_by_cluster[cluster.node_id]
            for atom_id in event_by_id[event_id].ordered_atom_ids
            if atom_by_id[atom_id].story_facing
        ]
        if not story_lines:
            raise ValueError("an exact visible major cluster has no story-facing event ownership")
        cluster_bounds.append((min(story_lines), max(story_lines)))
    cluster_starts = tuple(item[0] for item in cluster_bounds)
    if (
        not cluster_starts
        or not EXPECTED_PROLOGUE_START_RANGE[0]
        <= cluster_starts[0]
        <= EXPECTED_PROLOGUE_START_RANGE[1]
    ):
        raise ValueError("the visible Prologue cluster lost its story-facing evidence")
    if tuple(cluster_bounds) != tuple(item[1] for item in EXPECTED_MAJOR_MEMBERSHIP_BOUNDS):
        raise ValueError("exact visible map membership does not match frozen major cluster bounds")
    labels_by_bounds = {
        expected_bounds: label for label, expected_bounds in EXPECTED_MAJOR_MEMBERSHIP_BOUNDS
    }
    cluster_labels = tuple(labels_by_bounds[bounds] for bounds in cluster_bounds)
    if cluster_labels != EXPECTED_MAJOR_ORDER:
        raise ValueError("exact visible map order does not match frozen major event order")
    normally_visible_event_ids = {
        item.event_id
        for item in narrative_map.nodes
        if item.kind is not NarrativeNodeKind.TECHNICAL_COVERAGE and item.event_id is not None
    }
    if any(
        atom_by_id[atom_id].source_order[1] <= EXPECTED_SETUP_END_LINE
        for event_id in normally_visible_event_ids
        for atom_id in event_by_id[event_id].ordered_atom_ids
    ):
        raise ValueError("exact technical setup leaked into a normally visible story node")
    if cluster_starts[0] - 1 != EXPECTED_SETUP_END_LINE:
        raise ValueError("exact technical setup boundary changed")
    if cluster_starts[1] != EXPECTED_MAJOR_STARTS[0]:
        raise ValueError("exact Day 1 cluster no longer starts at its frozen anchor")

    line_by_node = {item.primary_node_id: item.source_order[1] for item in model.atoms}
    visible_choice_ids = {
        item.choice_id
        for item in narrative_map.nodes
        if item.kind is NarrativeNodeKind.CHOICE and item.choice_id is not None
    }
    visible_rejoin_ids = {
        item.rejoin_node_id
        for item in narrative_map.nodes
        if item.kind is NarrativeNodeKind.REJOIN and item.rejoin_node_id is not None
    }
    visible_arm_ids = {item.arm_id for item in narrative_map.nodes if item.arm_id is not None}
    for split_line in branch_pairs:
        regions = [
            item for item in canonical.regions if line_by_node.get(item.split_node_id) == split_line
        ]
        if len(regions) != 1:
            raise ValueError("an exact choice line lacks unique M10 region authority")
        region = regions[0]
        if region.id not in visible_choice_ids or region.merge_node_id not in visible_rejoin_ids:
            raise ValueError("exact choice/rejoin authority is not visible in the Narrative Map")
        arms = region.attributes.get("arms")
        expected_arm_ids = (
            {
                raw_arm.get("id")
                for raw_arm in arms
                if isinstance(raw_arm, Mapping) and isinstance(raw_arm.get("id"), str)
            }
            if isinstance(arms, Sequence) and not isinstance(arms, str | bytes)
            else set()
        )
        if not expected_arm_ids.issubset(visible_arm_ids):
            raise ValueError("exact choice arm authority is not visible in the Narrative Map")
    return _ExactObservations(cluster_starts, tuple(cluster_bounds), cluster_labels)


def evaluate_synthetic_manifest(path: Path) -> dict[str, JsonValue]:
    """Execute and validate every frozen provider-free synthetic topology."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or value.get("schema") != "m15-synthetic-acceptance-v1":
        raise ValueError("the M15 synthetic manifest schema is unsupported")
    cases = value.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, str | bytes):
        raise ValueError("the M15 synthetic manifest cases must be an array")
    expected = {
        "linear-dialogue",
        "frequent-pose-changes",
        "local-detour",
        "nested-local-detour",
        "persistent-branches",
        "call-occurrences",
        "loop",
        "terminal",
        "unresolved-transfer",
    }
    identifiers = {str(item.get("id")) for item in cases if isinstance(item, Mapping)}
    if identifiers != expected:
        raise ValueError("the M15 synthetic topology matrix is incomplete")
    results: dict[str, JsonValue] = {}
    for item in cases:
        if not isinstance(item, Mapping):
            raise ValueError("each M15 synthetic case must be an object")
        case_id = str(item.get("id"))
        raw_signals = item.get("signals")
        raw_expected = item.get("expected")
        if (
            not isinstance(raw_signals, Sequence)
            or isinstance(raw_signals, str | bytes)
            or not isinstance(raw_expected, Mapping)
        ):
            raise ValueError(f"synthetic case {case_id!r} is malformed")
        signals = tuple(str(signal) for signal in raw_signals)
        observed = _evaluate_synthetic_case(case_id, signals)
        expected_values = {str(key): value for key, value in raw_expected.items()}
        unexpected = {
            key: {"expected": value, "observed": observed.get(key)}
            for key, value in expected_values.items()
            if observed.get(key) != value
        }
        if unexpected:
            raise ValueError(f"synthetic case {case_id!r} failed: {unexpected}")
        results[case_id] = cast(JsonValue, observed)
    return {
        "schema": "m15-provider-free-synthetic-report-v1",
        "case_count": len(identifiers),
        "case_ids": cast(JsonValue, sorted(identifiers)),
        "results": results,
        "provider_calls": 0,
        "game_execution_count": 0,
    }


def _evaluate_synthetic_case(case_id: str, signals: tuple[str, ...]) -> dict[str, JsonValue]:
    """Run one authoritative synthetic topology through the complete Track A pipeline."""

    canonical, model = _synthetic_authority(case_id, signals)
    corridors = build_narrative_corridors(canonical, model)
    events = assemble_narrative_events(
        corridors,
        expected_atom_ids=(item.id for item in model.atoms),
    )
    narrative_map = build_narrative_map(canonical, events, corridors=corridors)
    map_nodes = {item.node_id: item for item in narrative_map.nodes}

    if case_id in {"linear-dialogue", "frequent-pose-changes"}:
        return {
            "event_count": len(events),
            "choice_count": sum(len(event.nested_choice_ids) for event in events),
            "complete_coverage": {atom_id for event in events for atom_id in event.ordered_atom_ids}
            == {item.id for item in model.atoms},
            "visual_changes_are_hard_boundaries": len(events) > 1,
        }

    if case_id == "local-detour":
        return {
            "temporary": any(event.temporary_container_id is not None for event in events),
            "arm_count": len({item.arm_id for item in narrative_map.nodes if item.arm_id}),
            "rejoin_count": sum(
                item.kind is NarrativeNodeKind.REJOIN for item in narrative_map.nodes
            ),
            "continuation_owned_once": sum(
                atom_id == "atom-continuation"
                for event in events
                for atom_id in event.ordered_atom_ids
            )
            == 1,
        }

    if case_id == "nested-local-detour":
        choice_node_ids = {
            item.choice_id: item.node_id
            for item in narrative_map.nodes
            if item.kind is NarrativeNodeKind.CHOICE and item.choice_id is not None
        }
        arms = [item for item in narrative_map.nodes if item.arm_id is not None]
        return {
            "temporary": bool(arms),
            "nested_choice_count": max(0, len(choice_node_ids) - 1),
            "arms_escape_container": any(
                item.choice_id not in choice_node_ids
                or item.parent_node_id != choice_node_ids[item.choice_id]
                for item in arms
            ),
        }

    if case_id == "persistent-branches":
        return {
            "temporary": any(event.temporary_container_id is not None for event in events),
            "lane_count": len({event.lane_id for event in events}),
            "invented_merge": any(
                item.kind.value == "persistent_merge" for item in narrative_map.edges
            ),
        }

    if case_id == "call-occurrences":
        occurrence_ids = {
            event.call_occurrence_id for event in events if event.call_occurrence_id is not None
        }
        return {
            "occurrence_count": len(occurrence_ids),
            "cross_occurrence_membership": any(
                len(
                    {
                        corridor.call_occurrence_id
                        for corridor in corridors
                        if corridor.corridor_id in event.ordered_corridor_ids
                        and corridor.call_occurrence_id is not None
                    }
                )
                > 1
                for event in events
            ),
        }

    if case_id == "loop":
        return {
            "loop_preserved": any(event.loop_id == "loop" for event in events)
            and any(item.kind.value == "loop" for item in narrative_map.edges),
            "invented_linearization": not any(
                item.kind.value == "loop" for item in narrative_map.edges
            ),
        }

    if case_id == "terminal":
        terminals = {
            item.node_id for item in narrative_map.nodes if item.kind is NarrativeNodeKind.TERMINAL
        }
        return {
            "terminal_preserved": bool(terminals),
            "invented_continuation": any(
                item.source_node_id in terminals for item in narrative_map.edges
            ),
        }
    if case_id == "unresolved-transfer":
        unresolved = {
            item.node_id
            for item in narrative_map.nodes
            if item.kind is NarrativeNodeKind.UNRESOLVED
        }
        return {
            "conservative_boundary": bool(unresolved)
            and any(item.kind.value == "unresolved" for item in narrative_map.edges),
            "invented_target": any(
                item.source_node_id in unresolved and item.target_node_id in map_nodes
                for item in narrative_map.edges
            ),
        }
    raise ValueError(f"unsupported synthetic case {case_id!r}")


def _synthetic_authority(
    case_id: str,
    signals: tuple[str, ...],
) -> tuple[CanonicalGraph, SceneModel]:
    """Construct minimal validated M10/M11 authority for one declared topology."""

    node_specs, edge_specs, region_specs = _synthetic_specs(case_id, signals)
    generation = f"synthetic-{case_id}"
    origins = {
        node_id: OriginReference("synthetic_nodes", node_id) for node_id, *_rest in node_specs
    }
    evidence = tuple(
        SourceEvidence(
            f"evidence-{node_id}",
            {
                "path": "synthetic.rpy",
                "start": {"line": index + 1, "column": 1},
                "end": {"line": index + 1, "column": 20},
            },
            f"synthetic {node_id}",
            (origins[node_id],),
            "physical_source",
        )
        for index, (node_id, *_rest) in enumerate(node_specs)
    )
    nodes = tuple(
        CanonicalNode(
            node_id,
            canonical_kind,
            f"graph-{node_id}",
            label,
            ReachabilityStatus.PROVEN_REACHABLE,
            (f"evidence-{node_id}",),
            (),
            (origins[node_id],),
            {"source_kind": source_kind, "source_text": label, **attributes},
        )
        for node_id, _atom_kind, canonical_kind, label, source_kind, attributes in node_specs
    )
    edges = tuple(
        CanonicalEdge(
            edge_id,
            source_id,
            target_id,
            kind,
            (
                ReachabilityStatus.PROVEN_REACHABLE
                if resolved
                else ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR
            ),
            resolved,
            (f"evidence-{source_id}",),
            (),
            (origins[source_id],),
            {"gate_ids": [], "effect_ids": [], "semantic_roles": [], **attributes},
        )
        for edge_id, source_id, target_id, kind, resolved, attributes in edge_specs
    )
    proofs = tuple(
        DerivedProof(
            f"proof-{region_id}",
            "synthetic_region",
            (origins[split_id],),
            tuple(member_ids),
            "Synthetic authoritative topology proof.",
        )
        for region_id, _kind, split_id, _merge_id, member_ids, _attributes in region_specs
    )
    regions = tuple(
        CanonicalRegion(
            region_id,
            kind,
            split_id,
            merge_id,
            tuple(member_ids),
            (origins[split_id],),
            (f"proof-{region_id}",),
            attributes,
        )
        for region_id, kind, split_id, merge_id, member_ids, attributes in region_specs
    )
    canonical = CanonicalGraph(
        generation,
        {"synthetic": generation},
        nodes,
        edges,
        regions,
        (),
        evidence,
        proofs,
    )
    canonical.validate()
    atoms = tuple(
        StoryAtom(
            f"atom-{node_id}",
            atom_kind,
            node_id,
            label,
            atom_kind not in {AtomKind.TECHNICAL, AtomKind.CONDITION},
            M11_ATOM_RULE_VERSION,
            M11Provenance(node_ids=(node_id,), evidence_ids=(f"evidence-{node_id}",)),
            source_kind,
            None,
            ("synthetic.rpy", index + 1, 1, node_id),
        )
        for index, (node_id, atom_kind, _kind, label, source_kind, _attrs) in enumerate(node_specs)
    )
    full_provenance = M11Provenance(
        node_ids=tuple(item.id for item in nodes),
        edge_ids=tuple(item.id for item in edges),
        region_ids=tuple(item.id for item in regions),
        evidence_ids=tuple(item.id for item in evidence),
        proof_ids=tuple(item.id for item in proofs),
    )
    boundary = BoundaryDecision(
        "boundary-entry",
        None,
        atoms[0].id,
        BoundaryStrength.HARD,
        DecisionStatus.ACCEPTED,
        M11_BOUNDARY_RULE_VERSION,
        (nodes[0].id,),
        M11Provenance(node_ids=(nodes[0].id,), evidence_ids=(evidence[0].id,)),
        "Synthetic entry boundary.",
        "entry_root",
    )
    scene = Scene(
        "scene-synthetic",
        "chapter-synthetic",
        "lane-spine",
        "Synthetic scene",
        0,
        tuple(item.id for item in atoms),
        (),
        (),
        SceneRepeatability.ONCE,
        None,
        boundary.id,
        False,
        full_provenance,
    )
    lane = PersistentLane(
        "lane-spine",
        LaneKind.SPINE,
        None,
        None,
        None,
        (scene.id,),
        None,
        None,
        full_provenance,
    )
    chapter = Chapter(
        "chapter-synthetic",
        "Synthetic",
        0,
        (lane.id,),
        (scene.id,),
        boundary.id,
        full_provenance,
    )
    coverage_entries = [
        CoverageEntry(
            CoverageCollection.NODE,
            node.id,
            CoverageDisposition.ATOM_OWNED,
            atoms[index].id,
            (),
            "Synthetic node ownership.",
        )
        for index, node in enumerate(nodes)
    ]
    coverage_entries.extend(
        CoverageEntry(
            collection,
            canonical_id,
            CoverageDisposition.STRUCTURAL_REFERENCE,
            None,
            (),
            "Synthetic structural authority.",
        )
        for collection, identifiers in (
            (CoverageCollection.EDGE, tuple(item.id for item in edges)),
            (CoverageCollection.REGION, tuple(item.id for item in regions)),
        )
        for canonical_id in identifiers
    )
    model = SceneModel(
        CanonicalBinding(generation, CANONICAL_GRAPH_SCHEMA, canonical.authority_hash),
        atoms,
        (boundary,),
        (scene,),
        (),
        (),
        (lane,),
        (chapter,),
        (),
        CanonicalCoverage(
            tuple(item.id for item in nodes),
            tuple(item.id for item in edges),
            tuple(item.id for item in regions),
            (),
            tuple(coverage_entries),
        ),
    )
    model.validate()
    return canonical, model


def _synthetic_specs(
    case_id: str,
    signals: tuple[str, ...],
) -> tuple[list[NodeSpec], list[EdgeSpec], list[RegionSpec]]:
    """Return node, edge, and region specifications without expected result flags."""

    def node(
        node_id: str,
        atom_kind: AtomKind = AtomKind.NARRATION,
        canonical_kind: CanonicalNodeKind = CanonicalNodeKind.SCRIPT_UNIT,
        label: str | None = None,
        source_kind: str = "statement",
        attributes: Mapping[str, object] | None = None,
    ) -> NodeSpec:
        return (
            node_id,
            atom_kind,
            canonical_kind,
            label or node_id.replace("_", " ").title(),
            source_kind,
            dict(attributes or {}),
        )

    def edge(
        edge_id: str,
        source_id: str,
        target_id: str,
        kind: str = "continuation",
        resolved: bool = True,
        attributes: Mapping[str, object] | None = None,
    ) -> EdgeSpec:
        return edge_id, source_id, target_id, kind, resolved, dict(attributes or {})

    nodes: list[NodeSpec]
    edges: list[EdgeSpec]
    regions: list[RegionSpec] = []
    if case_id == "linear-dialogue":
        nodes = [node("dialogue", AtomKind.DIALOGUE), node("narration")]
        edges = [edge("edge-0", "dialogue", "narration")]
    elif case_id == "frequent-pose-changes":
        nodes = [
            node("dialogue-0", AtomKind.DIALOGUE),
            node(
                "pose-0", AtomKind.VISUAL_CHANGE, label="Scene room pose one", source_kind="scene"
            ),
            node(
                "pose-1", AtomKind.VISUAL_CHANGE, label="Scene room pose two", source_kind="scene"
            ),
            node("dialogue-1", AtomKind.DIALOGUE),
        ]
        edges = [edge(f"edge-{index}", nodes[index][0], nodes[index + 1][0]) for index in range(3)]
    elif case_id == "local-detour":
        nodes = [
            node("choice_split", AtomKind.CHOICE, CanonicalNodeKind.CHOICE, source_kind="menu"),
            node("arm_0"),
            node("arm_1"),
            node("proven_rejoin", canonical_kind=CanonicalNodeKind.MERGE),
            node("continuation"),
        ]
        edges = [
            edge("edge-split-0", "choice_split", "arm_0", "choice"),
            edge("edge-split-1", "choice_split", "arm_1", "choice"),
            edge("edge-arm-0", "arm_0", "proven_rejoin"),
            edge("edge-arm-1", "arm_1", "proven_rejoin"),
            edge("edge-continuation", "proven_rejoin", "continuation"),
        ]
        regions = [
            _local_region("choice", "choice_split", "proven_rejoin", (("arm_0",), ("arm_1",)))
        ]
    elif case_id == "nested-local-detour":
        nodes = [
            node("choice_split", AtomKind.CHOICE, CanonicalNodeKind.CHOICE, source_kind="menu"),
            node("arm_0"),
            node("nested_choice", AtomKind.CHOICE, CanonicalNodeKind.CHOICE, source_kind="menu"),
            node("nested_arm_0"),
            node("nested_arm_1"),
            node("nested_rejoin", canonical_kind=CanonicalNodeKind.MERGE),
            node("arm_1"),
            node("proven_rejoin", canonical_kind=CanonicalNodeKind.MERGE),
        ]
        edges = [
            edge("edge-outer-0", "choice_split", "arm_0", "choice"),
            edge("edge-outer-1", "choice_split", "arm_1", "choice"),
            edge("edge-nested-entry", "arm_0", "nested_choice"),
            edge("edge-nested-0", "nested_choice", "nested_arm_0", "choice"),
            edge("edge-nested-1", "nested_choice", "nested_arm_1", "choice"),
            edge("edge-nested-merge-0", "nested_arm_0", "nested_rejoin"),
            edge("edge-nested-merge-1", "nested_arm_1", "nested_rejoin"),
            edge("edge-outer-merge-0", "nested_rejoin", "proven_rejoin"),
            edge("edge-outer-merge-1", "arm_1", "proven_rejoin"),
        ]
        regions = [
            _local_region(
                "choice",
                "choice_split",
                "proven_rejoin",
                (
                    ("arm_0", "nested_choice", "nested_arm_0", "nested_arm_1", "nested_rejoin"),
                    ("arm_1",),
                ),
            ),
            _local_region(
                "nested-choice",
                "nested_choice",
                "nested_rejoin",
                (("nested_arm_0",), ("nested_arm_1",)),
                parent="choice",
            ),
        ]
    elif case_id == "persistent-branches":
        lane_0 = {"route": {"lane_id": "lane_0"}}
        lane_1 = {"route": {"lane_id": "lane_1"}}
        nodes = [
            node(
                "persistent_split",
                AtomKind.CONDITION,
                CanonicalNodeKind.CONDITION,
                attributes=lane_0,
            ),
            node("lane_0", attributes=lane_0),
            node("lane_1", attributes=lane_1),
        ]
        edges = [
            edge("edge-lane-0", "persistent_split", "lane_0", "choice"),
            edge("edge-lane-1", "persistent_split", "lane_1", "choice"),
        ]
        regions = [
            (
                "persistent",
                "persistent_route",
                "persistent_split",
                None,
                ("persistent_split", "lane_0", "lane_1"),
                {
                    "arms": [
                        {
                            "id": "lane-arm-0",
                            "ordinal": 0,
                            "entry_node_id": "lane_0",
                            "member_node_ids": ["lane_0"],
                        },
                        {
                            "id": "lane-arm-1",
                            "ordinal": 1,
                            "entry_node_id": "lane_1",
                            "member_node_ids": ["lane_1"],
                        },
                    ]
                },
            )
        ]
    elif case_id == "call-occurrences":
        nodes = [
            node("call_0", AtomKind.CALL),
            node("callee_0"),
            node("return_0"),
            node("call_1", AtomKind.CALL),
            node("callee_1"),
            node("return_1"),
            node("tail"),
        ]
        edges = [
            edge(
                "edge-call-0",
                "call_0",
                "callee_0",
                "call",
                attributes={"call_site_id": "occurrence-0"},
            ),
            edge(
                "edge-callee-0", "callee_0", "return_0", attributes={"call_site_id": "occurrence-0"}
            ),
            edge(
                "edge-return-0",
                "return_0",
                "call_1",
                "call_return",
                attributes={"call_site_id": "occurrence-0"},
            ),
            edge(
                "edge-call-1",
                "call_1",
                "callee_1",
                "call",
                attributes={"call_site_id": "occurrence-1"},
            ),
            edge(
                "edge-callee-1", "callee_1", "return_1", attributes={"call_site_id": "occurrence-1"}
            ),
            edge(
                "edge-return-1",
                "return_1",
                "tail",
                "call_return",
                attributes={"call_site_id": "occurrence-1"},
            ),
        ]
    elif case_id == "loop":
        loop = {"loop_ids": ["loop"]}
        nodes = [
            node("entry"),
            node("loop_body", AtomKind.LOOP, CanonicalNodeKind.LOOP, attributes=loop),
            node("back_edge", attributes=loop),
            node("exit"),
        ]
        edges = [
            edge("edge-entry", "entry", "loop_body"),
            edge("edge-body", "loop_body", "back_edge"),
            edge("edge-back", "back_edge", "loop_body", "loop_back"),
            edge("edge-exit", "back_edge", "exit"),
        ]
    elif case_id == "terminal":
        nodes = [node("entry"), node("terminal", AtomKind.TERMINAL, CanonicalNodeKind.TERMINAL)]
        edges = [edge("edge-terminal", "entry", "terminal", "terminal")]
    elif case_id == "unresolved-transfer":
        nodes = [
            node("entry"),
            node("unresolved_transfer", AtomKind.UNRESOLVED, CanonicalNodeKind.UNRESOLVED),
        ]
        edges = [
            edge("edge-unresolved", "entry", "unresolved_transfer", "unresolved_transfer", False)
        ]
    else:
        raise ValueError(f"unsupported synthetic case {case_id!r}")
    if not signals:
        raise ValueError("synthetic acceptance cases require declared signals")
    return nodes, edges, regions


def _local_region(
    region_id: str,
    split_id: str,
    merge_id: str,
    arms: tuple[tuple[str, ...], ...],
    *,
    parent: str | None = None,
) -> RegionSpec:
    attributes: dict[str, object] = {
        "arms": [
            {
                "id": f"{region_id}-arm-{ordinal}",
                "ordinal": ordinal,
                "entry_node_id": members[0],
                "member_node_ids": list(members),
            }
            for ordinal, members in enumerate(arms)
        ]
    }
    if parent is not None:
        attributes["parent_region_id"] = parent
    members = (split_id, *(node_id for arm in arms for node_id in arm), merge_id)
    return region_id, "local_detour", split_id, merge_id, members, attributes


def _canonical_choice_pairs(
    canonical: CanonicalGraph,
    model: SceneModel,
) -> dict[int, int]:
    """Derive the four acceptance pairs from M10 regions and resolved outgoing edges."""

    line_by_node = {item.primary_node_id: item.source_order[1] for item in model.atoms}
    region_by_id = {item.id: item for item in canonical.regions}
    outgoing: dict[str, list[str]] = {}
    for edge in canonical.edges:
        if edge.resolved:
            outgoing.setdefault(edge.source_id, []).append(edge.target_id)
    temporary = {
        "local_detour",
        "optional_detour",
        "reconvergent_route_segment",
    }
    temporary_merge_nodes = {
        item.merge_node_id
        for item in canonical.regions
        if item.kind in temporary and item.merge_node_id is not None
    }
    result: dict[int, int] = {}
    for region in canonical.regions:
        split_line = line_by_node.get(region.split_node_id)
        if split_line not in EXPECTED_MENU_LINES:
            continue
        scope = region
        while True:
            explicit = scope.attributes.get("parent_region_id")
            candidates = [
                item
                for item in canonical.regions
                if item.id != scope.id
                and item.kind in temporary
                and scope.split_node_id in item.member_node_ids
            ]
            parent = (
                region_by_id.get(explicit)
                if isinstance(explicit, str)
                else min(candidates, key=lambda item: len(item.member_node_ids), default=None)
            )
            if parent is None or parent.kind not in temporary:
                break
            scope = parent
        if scope.merge_node_id is None:
            raise ValueError("a narrative choice lost its authoritative M10 merge")
        continuation_lines: list[int] = []
        pending = list(outgoing.get(scope.merge_node_id, ()))
        visited: set[str] = set()
        while pending:
            target = pending.pop()
            if target in visited:
                raise ValueError("a narrative choice continuation contains a merge cycle")
            visited.add(target)
            if target in temporary_merge_nodes:
                pending.extend(outgoing.get(target, ()))
            elif target in line_by_node:
                continuation_lines.append(line_by_node[target])
        if not continuation_lines:
            raise ValueError("a narrative choice lost its authoritative M10 continuation")
        result[int(split_line)] = max(continuation_lines)
    return result


def _read_authority(
    project_path: Path,
) -> tuple[
    dict[str, object],
    dict[str, Mapping[str, object]],
    dict[str, object] | None,
]:
    uri = f"file:{project_path.as_posix()}?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as database:
        canonical = _payload(database, "m10_canonical_graph", "authoritative")
        state = _payload(database, "m11_analysis_state", "authoritative")
        published = _mapping(state.get("published"), "published M11 binding")
        pointers = published.get("phases")
        if not isinstance(pointers, Sequence) or isinstance(pointers, str | bytes):
            raise ValueError("the published M11 phase pointers are invalid")
        results: dict[str, Mapping[str, object]] = {}
        for item in pointers:
            pointer = _mapping(item, "M11 phase pointer")
            phase = pointer.get("phase")
            key = pointer.get("record_key")
            if not isinstance(phase, str) or not isinstance(key, str):
                raise ValueError("an M11 phase pointer has invalid identity")
            envelope = _payload(database, "m11_phase_results", key)
            results[phase] = _mapping(envelope.get("result"), "M11 phase result")
        correction = _optional_payload(
            database,
            M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION,
            M15_LEADING_TECHNICAL_CORRECTION_KEY,
        )
    return canonical, results, correction


def _optional_payload(
    database: sqlite3.Connection,
    collection: str,
    record_key: str,
) -> dict[str, object] | None:
    row = database.execute(
        "SELECT payload_json FROM payloads WHERE collection=? AND record_key=?",
        (collection, record_key),
    ).fetchone()
    if row is None:
        return None
    if not isinstance(row[0], str | bytes):
        raise ValueError(f"project payload {collection}/{record_key} is corrupt")
    value = json.loads(row[0])
    if not isinstance(value, dict):
        raise ValueError(f"project payload {collection}/{record_key} is not an object")
    return cast(dict[str, object], value)


def _payload(
    database: sqlite3.Connection,
    collection: str,
    record_key: str,
) -> dict[str, object]:
    row = database.execute(
        "SELECT payload_json FROM payloads WHERE collection=? AND record_key=?",
        (collection, record_key),
    ).fetchone()
    if row is None or not isinstance(row[0], str | bytes):
        raise ValueError(f"missing project payload {collection}/{record_key}")
    value = json.loads(row[0])
    if not isinstance(value, dict):
        raise ValueError(f"project payload {collection}/{record_key} is not an object")
    return cast(dict[str, object], value)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _fingerprint(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


def _resolve_private_paths(fixture_root: Path, project_path: Path) -> tuple[Path, Path]:
    if (fixture_root / "input" / "game" / "v0.01_clean.rpy").is_file():
        return fixture_root, project_path
    base = Path.home() / "Documents" / "Codex" / "Renpy"
    fallback_root = base / "MsDay1"
    fallback_project = base / "tmp" / "msday1-sentinel-validation.rsmproj"
    return fallback_root, fallback_project if fallback_project.is_file() else project_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-root", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--comparison-project", type=Path)
    parser.add_argument(
        "--synthetic-manifest",
        type=Path,
        default=Path("tests/fixtures/m15/acceptance_cases.json"),
    )
    arguments = parser.parse_args()
    reports: dict[str, JsonValue] = {
        "synthetic": evaluate_synthetic_manifest(arguments.synthetic_manifest)
    }
    if arguments.fixture_root is not None and arguments.project is not None:
        reports["exact"] = evaluate_exact_msday1(
            arguments.fixture_root,
            arguments.project,
            arguments.comparison_project,
        )
    print(json.dumps(reports, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
