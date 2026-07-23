from __future__ import annotations

from dataclasses import replace

import pytest

from m15_test_support import linear_authority
from renpy_story_mapper.canonical_graph_contract import (
    CanonicalGraph,
    CanonicalRegion,
    DerivedProof,
    OriginReference,
)
from renpy_story_mapper.m11_scene_model import AtomKind, SceneModel
from renpy_story_mapper.narrative_map import (
    ChoiceComposition,
    EvidenceNavigation,
    FineNarrativeUnit,
    MajorCluster,
    SemanticBeat,
    SemanticClaimClass,
    SemanticOutline,
    SemanticPresentationRole,
    SemanticSummaryClaim,
    WholeScopeEditorialBatch,
    WholeScopeEditorialRecord,
    build_compact_whole_scope_projection,
    build_fine_narrative_units,
    stable_m15_id,
)
from renpy_story_mapper.narrative_map.adapters import bind_m15_authority
from renpy_story_mapper.narrative_map.contracts import NarrativeEdgeKind
from renpy_story_mapper.narrative_map.projection import (
    SemanticQuotientTopology,
    SemanticTopologyEdge,
    SemanticTopologyNode,
)
from renpy_story_mapper.narrative_map.semantic_projection import (
    choice_owns_visual_rejoin,
    project_compact_semantic_edges,
    project_compact_semantic_nodes,
    semantic_outline_hash,
)
from renpy_story_mapper.web.narrative_map_api import whole_scope_projection_page


def _summary(subject_kind: str, subject_id: str) -> dict[str, object]:
    return {
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "title": f"Synthetic {subject_kind} {subject_id}",
        "summary": "A generalized evidence-linked story summary.",
        "characters": [],
        "claims": [],
        "warnings": [],
    }


def _projection_fixture() -> tuple[
    CanonicalGraph,
    SceneModel,
    tuple[FineNarrativeUnit, ...],
    SemanticOutline,
    SemanticQuotientTopology,
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
    ChoiceComposition,
    ChoiceComposition,
]:
    canonical, model = linear_authority(
        (
            AtomKind.NARRATION,
            AtomKind.CHOICE,
            AtomKind.NARRATION,
            AtomKind.NARRATION,
            AtomKind.NARRATION,
            AtomKind.CHOICE,
            AtomKind.DIALOGUE,
            AtomKind.NARRATION,
            AtomKind.NARRATION,
        ),
        labels=(
            "Choose an age-gate setting",
            "Setup question",
            "Setup A",
            "Setup B",
            "The story begins",
            "What should the protagonist do?",
            "Take the path",
            "Stay behind",
            "The paths continue",
        ),
        source_kinds=(
            "narration",
            "menu",
            "narration",
            "narration",
            "narration",
            "menu",
            "dialogue",
            "narration",
            "narration",
        ),
    )
    raw_units = build_fine_narrative_units(canonical, model)
    setup_proof = DerivedProof(
        "proof-setup",
        "synthetic_rejoin",
        (OriginReference("synthetic", "region-setup"),),
        ("node-1", "node-4"),
        "Synthetic shallow setup choice rejoins before the story.",
    )
    story_proof = DerivedProof(
        "proof-story",
        "synthetic_rejoin",
        (OriginReference("synthetic", "region-story"),),
        ("node-5", "node-8"),
        "Synthetic rich story choice rejoins after its arms.",
    )
    canonical = replace(
        canonical,
        regions=(
            CanonicalRegion(
                "region-setup",
                "local_detour",
                "node-1",
                "node-4",
                ("node-2", "node-3"),
                (OriginReference("synthetic", "region-setup"),),
                (setup_proof.id,),
                {},
            ),
            CanonicalRegion(
                "region-story",
                "local_detour",
                "node-5",
                "node-8",
                ("node-6", "node-7"),
                (OriginReference("synthetic", "region-story"),),
                (story_proof.id,),
                {},
            ),
        ),
        proofs=(setup_proof, story_proof),
    )
    canonical.validate()
    model = replace(
        model,
        binding=replace(model.binding, canonical_hash=canonical.authority_hash),
    )
    authority = bind_m15_authority(canonical, model)
    raw_units = tuple(replace(unit, authority=authority) for unit in raw_units)
    technical_choice_id = "choice-setup"
    story_choice_id = "choice-story"
    owners = (
        (None, None),
        (None, None),
        (technical_choice_id, "setup-a"),
        (technical_choice_id, "setup-b"),
        (None, None),
        (None, None),
        (story_choice_id, "story-a"),
        (story_choice_id, "story-b"),
        (None, None),
    )
    units = tuple(
        replace(unit, parent_choice_id=choice_id, parent_arm_id=arm_id)
        for unit, (choice_id, arm_id) in zip(raw_units, owners, strict=True)
    )
    beat_ids = tuple(f"beat-{index}" for index in range(len(units)))
    clusters = ("cluster-setup", "cluster-story")
    beats = tuple(
        SemanticBeat(
            beat_id,
            clusters[0] if index < 4 else clusters[1],
            (unit.unit_id,),
            unit.parent_choice_id,
            unit.parent_arm_id,
            EvidenceNavigation("semantic_beat", beat_id),
        )
        for index, (beat_id, unit) in enumerate(zip(beat_ids, units, strict=True))
    )
    technical_choice = ChoiceComposition(
        technical_choice_id,
        clusters[0],
        None,
        None,
        ("setup-a", "setup-b"),
        ("Enable setup A", "Enable setup B"),
        (),
        ("setup-rejoin-a", "setup-rejoin-b"),
        "node-4",
        units[4].unit_id,
        "region-setup",
    )
    story_choice = ChoiceComposition(
        story_choice_id,
        clusters[1],
        None,
        None,
        ("story-a", "story-b"),
        ("Take the path", "Stay behind"),
        (),
        ("story-rejoin-a", "story-rejoin-b"),
        "node-8",
        units[8].unit_id,
        "region-story",
    )
    outline_clusters = (
        MajorCluster(
            clusters[0],
            0,
            beat_ids[:4],
            (technical_choice_id,),
            EvidenceNavigation("major_cluster", clusters[0]),
        ),
        MajorCluster(
            clusters[1],
            1,
            beat_ids[4:],
            (story_choice_id,),
            EvidenceNavigation("major_cluster", clusters[1]),
        ),
    )
    outline = SemanticOutline(
        units[0].authority,
        tuple(unit.unit_id for unit in units),
        (),
        beats,
        outline_clusters,
        (technical_choice, story_choice),
        (),
    )
    story_rejoin_id = stable_m15_id(
        "semantic_rejoin",
        {
            "canonical_hash": canonical.authority_hash,
            "canonical_node_id": story_choice.shared_target_id,
            "call_occurrence_path": [],
        },
    )
    topology = SemanticQuotientTopology(
        canonical.authority_hash,
        (
            *(
                SemanticTopologyNode(beat.beat_id, "beat", units[index].node_ids)
                for index, beat in enumerate(beats)
            ),
            SemanticTopologyNode(technical_choice_id, "choice", ("node-1",)),
            SemanticTopologyNode(story_choice_id, "choice", ("node-5",)),
            SemanticTopologyNode(story_rejoin_id, "rejoin", ("node-8",)),
            SemanticTopologyNode("technical-root", "structural_anchor", ("node-0",)),
        ),
        (
            SemanticTopologyEdge(
                "topology-story-a",
                story_choice_id,
                beat_ids[6],
                NarrativeEdgeKind.CHOICE_ARM,
                ("edge-5",),
                (),
                (),
                ("evidence-5",),
            ),
            SemanticTopologyEdge(
                "topology-story-b",
                story_choice_id,
                beat_ids[7],
                NarrativeEdgeKind.CHOICE_ARM,
                ("edge-6",),
                (),
                (),
                ("evidence-6",),
            ),
            SemanticTopologyEdge(
                "topology-story-a-rejoin",
                beat_ids[6],
                story_rejoin_id,
                NarrativeEdgeKind.REJOIN,
                ("edge-6",),
                (),
                (),
                ("evidence-6",),
            ),
            SemanticTopologyEdge(
                "topology-story-b-rejoin",
                beat_ids[7],
                story_rejoin_id,
                NarrativeEdgeKind.REJOIN,
                ("edge-7",),
                (),
                (),
                ("evidence-7",),
            ),
        ),
    )
    summaries = {
        **{beat.beat_id: _summary("beat", beat.beat_id) for beat in beats},
        **{
            cluster.cluster_id: _summary("major_cluster", cluster.cluster_id)
            for cluster in outline_clusters
        },
        technical_choice_id: _summary("choice", technical_choice_id),
        story_choice_id: _summary("choice", story_choice_id),
    }
    provenance = {
        subject_id: {"subject_id": subject_id}
        for subject_id in summaries
    }
    return (
        canonical,
        model,
        units,
        outline,
        topology,
        summaries,
        provenance,
        technical_choice,
        story_choice,
    )


def test_compact_projection_filters_front_matter_and_generic_routing_rows() -> None:
    (
        canonical,
        model,
        units,
        outline,
        topology,
        summaries,
        provenance,
        technical_choice,
        story_choice,
    ) = _projection_fixture()

    nodes = project_compact_semantic_nodes(
        canonical,
        model,
        units,
        outline,
        topology,
        summaries,
        provenance,
    )

    node_ids = {str(item["id"]) for item in nodes}
    assert technical_choice.choice_id not in node_ids
    assert "cluster-setup" not in node_ids
    assert "technical-root" not in node_ids
    assert story_choice.choice_id in node_ids
    assert not any(item["kind"] == "beat" for item in nodes)
    assert [item["title"] for item in nodes if item["kind"] == "choice_arm"] == [
        "Take the path",
        "Stay behind",
    ]


def test_compact_projection_orders_choice_then_exact_arms_then_proven_rejoin() -> None:
    (
        canonical,
        model,
        units,
        outline,
        topology,
        summaries,
        provenance,
        _technical_choice,
        story_choice,
    ) = _projection_fixture()

    nodes = project_compact_semantic_nodes(
        canonical,
        model,
        units,
        outline,
        topology,
        summaries,
        provenance,
    )

    choice = next(item for item in nodes if item["id"] == story_choice.choice_id)
    arms = [item for item in nodes if item["kind"] == "choice_arm"]
    rejoin = next(item for item in nodes if item["kind"] == "rejoin")
    assert [item["arm_id"] for item in arms] == list(story_choice.ordered_arm_ids)
    assert int(choice["order"]) < min(int(item["order"]) for item in arms)
    assert max(int(item["order"]) for item in arms) < int(rejoin["order"])
    assert rejoin["parent_node_id"] == story_choice.choice_id


def test_compact_projection_retains_exact_visible_choice_paths() -> None:
    (
        canonical,
        model,
        units,
        outline,
        topology,
        summaries,
        provenance,
        _technical_choice,
        story_choice,
    ) = _projection_fixture()
    nodes = project_compact_semantic_nodes(
        canonical,
        model,
        units,
        outline,
        topology,
        summaries,
        provenance,
    )

    edges = project_compact_semantic_edges(
        topology,
        tuple(str(item["id"]) for item in nodes),
    )

    visible_ids = {str(item["id"]) for item in nodes}
    assert edges
    assert all(edge.source_subject_id in visible_ids for edge in edges)
    assert all(edge.target_subject_id in visible_ids for edge in edges)
    assert {
        edge.target_subject_id
        for edge in edges
        if edge.source_subject_id == story_choice.choice_id
    } == {"beat-6", "beat-7"}
    assert all(edge.authority_edge_ids for edge in edges)


def test_nested_choice_without_own_continuation_uses_ancestor_visual_rejoin() -> None:
    outer = ChoiceComposition(
        "outer",
        "cluster-story",
        None,
        None,
        ("outer-a", "outer-b"),
        ("Continue", "Stop"),
        ("nested",),
        ("outer-rel-a", "outer-rel-b"),
        "outer-merge",
        "continuation-unit",
        "outer-region",
    )
    nested = ChoiceComposition(
        "nested",
        "cluster-story",
        "outer",
        "outer-a",
        ("nested-a", "nested-b"),
        ("Accept", "Decline"),
        (),
        ("nested-rel-a", "nested-rel-b"),
        "nested-merge",
        None,
        "nested-region",
    )
    choices = {outer.choice_id: outer, nested.choice_id: nested}

    assert choice_owns_visual_rejoin(outer, choices, {"outer", "nested"})
    assert not choice_owns_visual_rejoin(nested, choices, {"outer", "nested"})
    assert nested.rejoin_relationship_ids == ("nested-rel-a", "nested-rel-b")


def _whole_scope_editorial(
    outline: SemanticOutline,
    units: tuple[FineNarrativeUnit, ...],
) -> tuple[WholeScopeEditorialBatch, dict[str, dict[str, object]]]:
    unit_by_id = {item.unit_id: item for item in units}
    beat_by_id = {item.beat_id: item for item in outline.beats}
    evidence_by_subject: dict[str, set[str]] = {
        beat.beat_id: {
            evidence_id
            for unit_id in beat.ordered_unit_ids
            for evidence_id in unit_by_id[unit_id].evidence_ids
        }
        for beat in outline.beats
    }
    for cluster in outline.clusters:
        evidence_by_subject[cluster.cluster_id] = {
            evidence_id
            for beat_id in cluster.ordered_beat_ids
            for evidence_id in evidence_by_subject[beat_by_id[beat_id].beat_id]
        }
    for choice in outline.choices:
        evidence_by_subject[choice.choice_id] = {
            evidence_id
            for beat in outline.beats
            if beat.parent_choice_id == choice.choice_id
            for evidence_id in evidence_by_subject[beat.beat_id]
        }

    records: list[WholeScopeEditorialRecord] = []
    subjects = (
        *(("beat", item.beat_id, item.parent_cluster_id) for item in outline.beats),
        *(("major_cluster", item.cluster_id, item.cluster_id) for item in outline.clusters),
        *(("choice", item.choice_id, item.parent_cluster_id) for item in outline.choices),
    )
    for subject_kind, subject_id, cluster_id in subjects:
        role = (
            SemanticPresentationRole.FRONT_MATTER
            if cluster_id == "cluster-setup"
            else SemanticPresentationRole.STORY
        )
        if subject_id == "beat-8":
            role = SemanticPresentationRole.SCOPE_MARKER
        evidence_id = sorted(evidence_by_subject[subject_id])[0]
        records.append(
            WholeScopeEditorialRecord(
                subject_kind,
                subject_id,
                f"membership-{subject_id}",
                role,
                f"Synthetic {subject_kind} {subject_id}",
                f"The synthetic {subject_id} develops from beginning to end.",
                ("Character A",),
                (
                    SemanticSummaryClaim(
                        SemanticClaimClass.FACTUAL,
                        f"Synthetic evidence supports {subject_id}.",
                        (evidence_id,),
                    ),
                ),
            )
        )
    batch = WholeScopeEditorialBatch(
        "scope-synthetic",
        semantic_outline_hash(outline),
        tuple(records),
    )
    return batch, {
        item.subject_id: {
            "subject_id": item.subject_id,
            "logical_job_id": f"logical-{item.subject_id}",
            "transport_batch_id": "transport-editorial-synthetic",
        }
        for item in records
    }


def test_whole_scope_projection_filters_roles_and_preserves_exact_arm_identity() -> None:
    canonical, model, units, outline, topology, *_rest = _projection_fixture()
    batch, provenance = _whole_scope_editorial(outline, units)

    projection = build_compact_whole_scope_projection(
        canonical,
        model,
        units,
        outline,
        topology,
        batch,
        provenance,
    )

    assert projection.visible_row_count == 5
    assert {item["kind"] for item in projection.nodes} == {
        "major_cluster",
        "choice",
        "choice_arm",
        "rejoin",
    }
    assert "cluster-setup" in projection.omitted_subject_ids
    assert "choice-setup" in projection.omitted_subject_ids
    assert "beat-8" in projection.omitted_subject_ids
    arms = [item for item in projection.nodes if item["kind"] == "choice_arm"]
    assert [item["title"] for item in arms] == ["Take the path", "Stay behind"]
    assert [item["arm_id"] for item in arms] == ["story-a", "story-b"]
    assert all(item["id"] not in {"beat-6", "beat-7"} for item in arms)
    assert [item["member_subject_ids"] for item in arms] == [["beat-6"], ["beat-7"]]
    assert all(item["member_unit_ids"] for item in arms)
    assert all(item["evidence_ids"] for item in arms)
    assert all(item["navigation"]["target_id"] == item["id"] for item in arms)
    assert all(
        edge.source_subject_id in {str(item["id"]) for item in projection.nodes}
        and edge.target_subject_id in {str(item["id"]) for item in projection.nodes}
        for edge in projection.edges
    )


def test_whole_scope_projection_orders_choice_arms_and_rejoin_and_reports_density() -> None:
    canonical, model, units, outline, topology, *_rest = _projection_fixture()
    batch, provenance = _whole_scope_editorial(outline, units)
    projection = build_compact_whole_scope_projection(
        canonical,
        model,
        units,
        outline,
        topology,
        batch,
        provenance,
    )
    order = {str(item["id"]): int(item["order"]) for item in projection.nodes}
    choice = next(item for item in projection.nodes if item["kind"] == "choice")
    arms = [item for item in projection.nodes if item["kind"] == "choice_arm"]
    rejoin = next(item for item in projection.nodes if item["kind"] == "rejoin")
    assert order[str(choice["id"])] < min(order[str(item["id"])] for item in arms)
    assert max(order[str(item["id"])] for item in arms) < order[str(rejoin["id"])]

    page = whole_scope_projection_page(
        projection,
        authority_hash=canonical.authority_hash,
        publication_hash="a" * 64,
        build_id="build-synthetic",
    )
    assert page["provider_calls"] == 0
    assert page["m12_requests"] == 0
    page_nodes = page["nodes"]
    page_edges = page["edges"]
    assert isinstance(page_nodes, list) and isinstance(page_edges, list)
    for item in page_nodes:
        assert isinstance(item, dict)
        navigation = item["navigation"]
        assert isinstance(navigation, dict) and navigation["target_id"] == item["id"]
    for item in page_edges:
        assert isinstance(item, dict)
        navigation = item["navigation"]
        assert isinstance(navigation, dict) and navigation["target_id"] == item["id"]
        assert item["evidence_ids"]
    assert page["density"] == {
        "visible_rows": 5,
        "maximum_visible_rows": 32,
        "major_sections": 1,
        "choices": 1,
        "choice_arms": 2,
        "rejoins": 1,
    }


def test_whole_scope_projection_marks_ambiguous_arm_partial_and_rejects_foreign_evidence() -> None:
    canonical, model, units, outline, topology, *_rest = _projection_fixture()
    batch, provenance = _whole_scope_editorial(outline, units)
    partial_batch = replace(
        batch,
        records=tuple(
            replace(item, warnings=("Synthetic ambiguity remains.",))
            if item.subject_id == "beat-6"
            else item
            for item in batch.records
        ),
    )
    projection = build_compact_whole_scope_projection(
        canonical,
        model,
        units,
        outline,
        topology,
        partial_batch,
        provenance,
    )
    partial_arm = next(
        item
        for item in projection.nodes
        if item.get("kind") == "choice_arm" and item.get("arm_id") == "story-a"
    )
    assert partial_arm["editorial_status"] == "partial"
    assert partial_arm["warnings"] == ["Synthetic ambiguity remains."]
    assert partial_arm["id"] in projection.partial_subject_ids
    partial_page = whole_scope_projection_page(
        projection,
        authority_hash=canonical.authority_hash,
        publication_hash="b" * 64,
        build_id="build-partial-synthetic",
    )
    assert partial_page["build_state"] == "partial"

    original = next(item for item in batch.records if item.subject_id == "beat-6")
    foreign = replace(
        original,
        claims=(
            SemanticSummaryClaim(
                SemanticClaimClass.FACTUAL,
                "A claim cites evidence outside the frozen subject.",
                ("evidence-foreign",),
            ),
        ),
    )
    invalid_batch = replace(
        batch,
        records=tuple(
            foreign if item.subject_id == foreign.subject_id else item
            for item in batch.records
        ),
    )
    with pytest.raises(ValueError, match="foreign evidence"):
        build_compact_whole_scope_projection(
            canonical,
            model,
            units,
            outline,
            topology,
            invalid_batch,
            provenance,
        )
