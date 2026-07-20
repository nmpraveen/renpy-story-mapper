from __future__ import annotations

from collections.abc import Sequence

from renpy_story_mapper.canonical_graph_contract import (
    CANONICAL_GRAPH_SCHEMA,
    CanonicalEdge,
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeKind,
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
    Provenance,
    Scene,
    SceneModel,
    SceneRepeatability,
    StoryAtom,
)


def linear_authority(
    kinds: Sequence[AtomKind],
    *,
    labels: Sequence[str] | None = None,
    source_kinds: Sequence[str] | None = None,
    edge_attributes: Sequence[dict[str, object]] | None = None,
) -> tuple[CanonicalGraph, SceneModel]:
    labels = labels or tuple(f"Synthetic item {index}" for index in range(len(kinds)))
    source_kinds = source_kinds or tuple("statement" for _ in kinds)
    origins = tuple(OriginReference("graph_nodes", f"graph-{index}") for index in range(len(kinds)))
    evidence = tuple(
        SourceEvidence(
            f"evidence-{index}",
            {
                "path": "game/synthetic.rpy",
                "start": {"line": index + 1, "column": 1},
                "end": {"line": index + 1, "column": 20},
            },
            f"synthetic source {index}",
            (origins[index],),
            "physical_source",
        )
        for index in range(len(kinds))
    )
    nodes = tuple(
        CanonicalNode(
            id=f"node-{index}",
            kind=_canonical_kind(kind),
            graph_node_id=f"graph-{index}",
            label=labels[index],
            reachability=ReachabilityStatus.PROVEN_REACHABLE,
            evidence_ids=(f"evidence-{index}",),
            proof_ids=(),
            origins=(origins[index],),
            attributes={},
        )
        for index, kind in enumerate(kinds)
    )
    edges = tuple(
        CanonicalEdge(
            id=f"edge-{index}",
            source_id=f"node-{index}",
            target_id=f"node-{index + 1}",
            kind="continuation",
            reachability=ReachabilityStatus.PROVEN_REACHABLE,
            resolved=True,
            evidence_ids=(f"evidence-{index}",),
            proof_ids=(),
            origins=(origins[index],),
            attributes=(
                edge_attributes[index]
                if edge_attributes is not None
                else {"gate_ids": [], "effect_ids": [], "semantic_roles": []}
            ),
        )
        for index in range(len(kinds) - 1)
    )
    canonical = CanonicalGraph(
        "generation-synthetic",
        {"graph": "generation-synthetic"},
        nodes,
        edges,
        (),
        (),
        evidence,
        (),
    )
    canonical.validate()
    model_provenance = Provenance(
        node_ids=tuple(item.id for item in nodes),
        edge_ids=tuple(item.id for item in edges),
        evidence_ids=tuple(item.id for item in evidence),
    )
    atoms = tuple(
        StoryAtom(
            id=f"atom-{index}",
            kind=kind,
            primary_node_id=f"node-{index}",
            label=labels[index],
            story_facing=kind not in {AtomKind.TECHNICAL, AtomKind.CONDITION},
            rule_id=M11_ATOM_RULE_VERSION,
            provenance=Provenance(
                node_ids=(f"node-{index}",),
                evidence_ids=(f"evidence-{index}",),
            ),
            source_kind=source_kinds[index],
            speaker=None,
            source_order=("game/synthetic.rpy", index + 1, 1, f"node-{index}"),
        )
        for index, kind in enumerate(kinds)
    )
    boundary = BoundaryDecision(
        "boundary-entry",
        None,
        atoms[0].id,
        BoundaryStrength.HARD,
        DecisionStatus.ACCEPTED,
        M11_BOUNDARY_RULE_VERSION,
        (nodes[0].id,),
        Provenance(node_ids=(nodes[0].id,), evidence_ids=(evidence[0].id,)),
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
        model_provenance,
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
        model_provenance,
    )
    chapter = Chapter(
        "chapter-synthetic",
        "Synthetic",
        0,
        (lane.id,),
        (scene.id,),
        boundary.id,
        model_provenance,
    )
    entries = [
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
    entries.extend(
        CoverageEntry(
            CoverageCollection.EDGE,
            edge.id,
            CoverageDisposition.COLLAPSED_SUPPORT,
            None,
            (),
            "Synthetic edge support.",
        )
        for edge in edges
    )
    coverage = CanonicalCoverage(
        tuple(item.id for item in nodes),
        tuple(item.id for item in edges),
        (),
        (),
        tuple(entries),
    )
    model = SceneModel(
        CanonicalBinding(
            canonical.source_generation,
            CANONICAL_GRAPH_SCHEMA,
            canonical.authority_hash,
        ),
        atoms,
        (boundary,),
        (scene,),
        (),
        (),
        (lane,),
        (chapter,),
        (),
        coverage,
    )
    model.validate()
    return canonical, model


def _canonical_kind(kind: AtomKind) -> CanonicalNodeKind:
    if kind is AtomKind.CHOICE:
        return CanonicalNodeKind.CHOICE
    if kind is AtomKind.CONDITION:
        return CanonicalNodeKind.CONDITION
    if kind is AtomKind.LOOP:
        return CanonicalNodeKind.LOOP
    if kind is AtomKind.TERMINAL:
        return CanonicalNodeKind.TERMINAL
    if kind is AtomKind.UNRESOLVED:
        return CanonicalNodeKind.UNRESOLVED
    return CanonicalNodeKind.SCRIPT_UNIT
