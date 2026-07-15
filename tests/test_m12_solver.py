from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from renpy_story_mapper.canonical_graph_contract import (
    CANONICAL_GRAPH_SCHEMA,
    CanonicalEdge,
    CanonicalFact,
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeKind,
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
    CallSiteOccurrence,
    CanonicalBinding,
    CanonicalCoverage,
    Chapter,
    CoverageCollection,
    CoverageDisposition,
    CoverageEntry,
    DecisionStatus,
    LaneKind,
    OccurrenceKind,
    PersistentLane,
    Provenance,
    Scene,
    SceneModel,
    SceneRepeatability,
    StoryAtom,
)
from renpy_story_mapper.m12_model import (
    DestinationKind,
    DeterministicLimitProfile,
    InitialStateValue,
    InitialValueKind,
    RequirementSource,
    RouteDestination,
    RouteRequest,
    StateVariableIdentity,
    TechnicalStatus,
)
from renpy_story_mapper.m12_solver import bind_route_request, numeric_projection, solve_route


def _fact(
    fact_id: str,
    *,
    kind: str,
    expression: str,
    variable: str | None = None,
    operation: str | None = None,
    value: object = None,
    status: str = "proven",
    initialization: bool = False,
) -> CanonicalFact:
    attributes: dict[str, object] = {"original_expression": expression}
    if kind == "requirement":
        attributes["variables"] = [variable] if variable is not None else []
    else:
        attributes.update({"variable": variable, "operation": operation, "value": value})
        if initialization:
            attributes["initialization"] = True
    return CanonicalFact(
        fact_id,
        kind,
        status,
        (f"evidence-{fact_id}",),
        (OriginReference("test_facts", fact_id),),
        attributes,
    )


def _authority(
    node_ids: Sequence[str],
    edge_specs: Sequence[Mapping[str, object]],
    *,
    facts: Sequence[CanonicalFact] = (),
    node_facts: Mapping[str, Sequence[str]] | None = None,
    scene_groups: Mapping[str, Sequence[str]] | None = None,
    node_kinds: Mapping[str, CanonicalNodeKind] | None = None,
    repeatable_scenes: Sequence[str] = (),
    occurrence: tuple[str, str, str, str] | None = None,
) -> tuple[CanonicalGraph, SceneModel]:
    node_facts = node_facts or {}
    node_kinds = node_kinds or {}
    evidence = [
        SourceEvidence(
            f"evidence-{node_id}",
            {"path": "story.rpy", "start_line": index + 1, "end_line": index + 1},
            node_id,
            (OriginReference("test_nodes", node_id),),
        )
        for index, node_id in enumerate(node_ids)
    ]
    evidence.extend(
        SourceEvidence(
            f"evidence-{fact.id}",
            {"path": "story.rpy", "start_line": 100 + index, "end_line": 100 + index},
            str(fact.attributes.get("original_expression", "")),
            fact.origins,
        )
        for index, fact in enumerate(facts)
    )
    root_proof = DerivedProof(
        "proof-root",
        "resolved_static_reachability",
        (OriginReference("test_nodes", "root"),),
        ("root",),
        "The configured test entry is the deterministic root.",
    )
    nodes = []
    for node_id in node_ids:
        attributes: dict[str, object] = {
            "resolved_static_reachable": True,
            "fact_ids": list(node_facts.get(node_id, ())),
        }
        proof_ids: tuple[str, ...] = ()
        if node_id == "root":
            attributes["reachability_witness"] = {
                "kind": "root",
                "root_node_id": "root",
                "node_id": "root",
            }
            proof_ids = (root_proof.id,)
        nodes.append(
            CanonicalNode(
                node_id,
                node_kinds.get(node_id, CanonicalNodeKind.SCRIPT_UNIT),
                node_id,
                node_id,
                ReachabilityStatus.PROVEN_REACHABLE,
                (f"evidence-{node_id}",),
                proof_ids,
                (OriginReference("test_nodes", node_id),),
                attributes,
            )
        )
    edges = []
    for spec in edge_specs:
        edge_id = str(spec["id"])
        resolved = bool(spec.get("resolved", True))
        attributes: dict[str, object] = {
            "gate_ids": list(spec.get("gates", ())),
            "effect_ids": list(spec.get("effects", ())),
            "predicate": spec.get("predicate"),
            "call_site_id": spec.get("call_site_id"),
        }
        edges.append(
            CanonicalEdge(
                edge_id,
                str(spec["source"]),
                str(spec["target"]),
                str(spec.get("kind", "flow")),
                (
                    ReachabilityStatus.PROVEN_REACHABLE
                    if resolved
                    else ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR
                ),
                resolved,
                (f"evidence-{spec['source']}", f"evidence-{spec['target']}"),
                (),
                (OriginReference("test_edges", edge_id),),
                attributes,
            )
        )
    graph = CanonicalGraph(
        "generation",
        {"test": "generation"},
        tuple(nodes),
        tuple(edges),
        (),
        tuple(facts),
        tuple(evidence),
        (root_proof,),
    )
    graph.validate()

    if scene_groups is None:
        scene_groups = {f"scene-{item}": (item,) for item in node_ids}
    scene_id_by_node = {
        node_id: scene_id for scene_id, members in scene_groups.items() for node_id in members
    }
    atoms = tuple(
        StoryAtom(
            f"atom-{node_id}",
            (
                AtomKind.CHOICE
                if node_kinds.get(node_id) is CanonicalNodeKind.CHOICE
                else AtomKind.DIALOGUE
            ),
            node_id,
            node_id,
            True,
            M11_ATOM_RULE_VERSION,
            Provenance(node_ids=(node_id,), evidence_ids=(f"evidence-{node_id}",)),
            source_kind="statement",
            source_order=("story.rpy", index + 1, index + 1, node_id),
        )
        for index, node_id in enumerate(node_ids)
    )
    boundaries = tuple(
        BoundaryDecision(
            f"boundary-{scene_id}",
            None,
            f"atom-{members[0]}",
            BoundaryStrength.HARD,
            DecisionStatus.ACCEPTED,
            M11_BOUNDARY_RULE_VERSION,
            (members[0],),
            Provenance(node_ids=tuple(members)),
            "The synthetic scene begins at a verified narrative atom.",
            "test_boundary",
        )
        for scene_id, members in scene_groups.items()
    )
    occurrence_record: CallSiteOccurrence | None = None
    if occurrence is not None:
        occurrence_id, caller_node, target_node, call_edge_id = occurrence
        occurrence_record = CallSiteOccurrence(
            occurrence_id,
            f"atom-{caller_node}",
            target_node,
            OccurrenceKind.NARRATIVE,
            scene_id_by_node[caller_node],
            "lane-spine",
            (f"atom-{target_node}",),
            (),
            False,
            False,
            Provenance(
                node_ids=(caller_node, target_node),
                edge_ids=(call_edge_id,),
            ),
        )
    scenes = tuple(
        Scene(
            scene_id,
            "chapter",
            "lane-spine",
            scene_id.replace("scene-", "").replace("-", " ").title(),
            index,
            tuple(f"atom-{item}" for item in members),
            (),
            (
                (occurrence_record.id,)
                if occurrence_record is not None
                and scene_id == occurrence_record.scene_id
                else ()
            ),
            (
                SceneRepeatability.REPEATABLE
                if scene_id in repeatable_scenes
                else SceneRepeatability.ONCE
            ),
            None,
            f"boundary-{scene_id}",
            False,
            Provenance(node_ids=tuple(members)),
        )
        for index, (scene_id, members) in enumerate(scene_groups.items())
    )
    all_scene_ids = tuple(item.id for item in scenes)
    all_nodes = tuple(node_ids)
    all_edges = tuple(item.id for item in edges)
    all_facts = tuple(item.id for item in facts)
    lane = PersistentLane(
        "lane-spine",
        LaneKind.SPINE,
        None,
        None,
        None,
        all_scene_ids,
        None,
        None,
        Provenance(node_ids=all_nodes),
    )
    chapter = Chapter(
        "chapter",
        "Story",
        0,
        (lane.id,),
        all_scene_ids,
        boundaries[0].id,
        Provenance(node_ids=all_nodes),
    )
    coverage_entries = [
        CoverageEntry(
            CoverageCollection.NODE,
            node_id,
            CoverageDisposition.ATOM_OWNED,
            f"atom-{node_id}",
            (),
            "The canonical node has exactly one M11 atom owner.",
        )
        for node_id in all_nodes
    ]
    coverage_entries.extend(
        CoverageEntry(
            CoverageCollection.EDGE,
            edge_id,
            CoverageDisposition.COLLAPSED_SUPPORT,
            None,
            (),
            "The canonical edge remains exact structural support.",
        )
        for edge_id in all_edges
    )
    coverage_entries.extend(
        CoverageEntry(
            CoverageCollection.FACT,
            fact_id,
            CoverageDisposition.COLLAPSED_SUPPORT,
            None,
            (),
            "The canonical fact remains exact state support.",
        )
        for fact_id in all_facts
    )
    model = SceneModel(
        CanonicalBinding("generation", CANONICAL_GRAPH_SCHEMA, graph.authority_hash),
        atoms,
        boundaries,
        scenes,
        (),
        ((occurrence_record,) if occurrence_record is not None else ()),
        (lane,),
        (chapter,),
        (),
        CanonicalCoverage(
            all_nodes,
            all_edges,
            (),
            all_facts,
            tuple(coverage_entries),
        ),
    )
    model.validate()
    return graph, model


def _solve(
    graph: CanonicalGraph,
    model: SceneModel,
    destination: RouteDestination,
    *,
    initial: Sequence[InitialStateValue] = (),
    limits: DeterministicLimitProfile | None = None,
) -> RouteRequest:
    return bind_route_request(
        graph,
        model,
        destination,
        initial_state=initial,
        limits=limits,
    )


def test_known_literal_default_confirms_while_unknown_and_persistent_remain_conservative() -> None:
    gate = _fact("gate", kind="requirement", expression="score >= 2", variable="score")
    initial_score = _fact(
        "m10-init",
        kind="effect",
        expression="default score = 2",
        variable="score",
        operation="assignment",
        value=2,
        initialization=True,
    )
    graph, model = _authority(
        ("root", "target"),
        ({"id": "edge", "source": "root", "target": "target", "gates": (gate.id,)},),
        facts=(gate, initial_score),
        node_facts={"root": (initial_score.id,)},
    )
    destination = RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target")
    score = StateVariableIdentity("store", "score", None)

    known_request = _solve(
        graph,
        model,
        destination,
        initial=(
            InitialStateValue(
                score,
                InitialValueKind.KNOWN,
                2,
                ("evidence-m10-init",),
            ),
        ),
    )
    known_result = solve_route(graph, model, known_request).result
    assert known_result is not None
    assert known_result.status is TechnicalStatus.CONFIRMED
    assert known_result.recommended is not None
    assert known_result.recommended.requirements[0].satisfying_effect_id == "m10-init"

    unknown_graph, unknown_model = _authority(
        ("root", "target"),
        ({"id": "edge", "source": "root", "target": "target", "gates": (gate.id,)},),
        facts=(gate,),
    )
    unknown_result = solve_route(
        unknown_graph,
        unknown_model,
        _solve(unknown_graph, unknown_model, destination),
    ).result
    assert unknown_result is not None
    assert unknown_result.status is TechnicalStatus.BEST_KNOWN
    assert unknown_result.recommended is not None
    assert unknown_result.recommended.requirements[0].source is RequirementSource.UNKNOWN

    persistent = StateVariableIdentity("persistent", "score", True)
    persistent_result = solve_route(
        unknown_graph,
        unknown_model,
        _solve(
            unknown_graph,
            unknown_model,
            destination,
            initial=(InitialStateValue(persistent, InitialValueKind.UNKNOWN),),
        ),
    ).result
    assert persistent_result is not None
    assert persistent_result.status is TechnicalStatus.BEST_KNOWN


def test_store_scoped_same_name_does_not_satisfy_another_store_gate() -> None:
    gate = _fact(
        "gate", kind="requirement", expression="store_a.score >= 1", variable="store_a.score"
    )
    graph, model = _authority(
        ("root", "target"),
        ({"id": "edge", "source": "root", "target": "target", "gates": (gate.id,)},),
        facts=(gate,),
    )
    destination = RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target")
    wrong_store = InitialStateValue(
        StateVariableIdentity("store_b", "score", None),
        InitialValueKind.ENTRY_PRECONDITION,
        1,
    )
    right_store = InitialStateValue(
        StateVariableIdentity("store_a", "score", None),
        InitialValueKind.ENTRY_PRECONDITION,
        1,
    )

    wrong = solve_route(
        graph, model, _solve(graph, model, destination, initial=(wrong_store,))
    ).result
    right = solve_route(
        graph, model, _solve(graph, model, destination, initial=(right_store,))
    ).result
    assert wrong is not None and wrong.status is TechnicalStatus.BEST_KNOWN
    assert right is not None and right.status is TechnicalStatus.PREREQUISITES


def test_known_initial_value_requires_exact_start_fact_and_evidence() -> None:
    graph, model = _authority(
        ("root", "target"),
        ({"id": "edge", "source": "root", "target": "target"},),
    )
    fabricated = InitialStateValue(
        StateVariableIdentity("store", "score", None),
        InitialValueKind.KNOWN,
        2,
        ("evidence-does-not-exist",),
    )

    with pytest.raises(ValueError, match="lacks exact M10 initialization proof"):
        _solve(
            graph,
            model,
            RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
            initial=(fabricated,),
        )


def test_compound_gate_preserves_effect_and_entry_precondition_attributions() -> None:
    gate = _fact(
        "compound-gate",
        kind="requirement",
        expression="a >= 1 and b >= 1",
    )
    set_a = _fact(
        "set-a",
        kind="effect",
        expression="a = 1",
        variable="a",
        operation="assignment",
        value=1,
    )
    graph, model = _authority(
        ("root", "build", "target"),
        (
            {
                "id": "build",
                "source": "root",
                "target": "build",
                "effects": (set_a.id,),
            },
            {
                "id": "finish",
                "source": "build",
                "target": "target",
                "gates": (gate.id,),
            },
        ),
        facts=(gate, set_a),
    )
    request = _solve(
        graph,
        model,
        RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
        initial=(
            InitialStateValue(
                StateVariableIdentity("store", "b", None),
                InitialValueKind.ENTRY_PRECONDITION,
                1,
            ),
        ),
    )

    result = solve_route(graph, model, request).result

    assert result is not None and result.recommended is not None
    assert result.status is TechnicalStatus.PREREQUISITES
    assert {
        (item.variable.name if item.variable else "", item.source)
        for item in result.recommended.requirements
    } == {
        ("a", RequirementSource.PROVEN_EFFECT),
        ("b", RequirementSource.ENTRY_PRECONDITION),
    }


def test_single_anchor_retains_materially_distinct_alternative() -> None:
    graph, model = _authority(
        ("root", "middle", "target"),
        (
            {"id": "direct", "source": "root", "target": "target"},
            {"id": "via", "source": "root", "target": "middle"},
            {"id": "finish", "source": "middle", "target": "target"},
        ),
    )
    result = solve_route(
        graph,
        model,
        _solve(
            graph,
            model,
            RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
        ),
    ).result

    assert result is not None and result.recommended is not None
    assert result.recommended.edge_ids == ("direct",)
    assert [item.edge_ids for item in result.alternatives] == [("via", "finish")]
    assert result.exhaustive and result.complete


def test_internally_built_score_outranks_equivalent_entry_precondition() -> None:
    gate = _fact("gate", kind="requirement", expression="score >= 2", variable="score")
    set_score = _fact(
        "set-score",
        kind="effect",
        expression="score = 2",
        variable="score",
        operation="assignment",
        value=2,
    )
    graph, model = _authority(
        ("root", "build", "target"),
        (
            {"id": "direct", "source": "root", "target": "target", "gates": (gate.id,)},
            {"id": "build", "source": "root", "target": "build", "effects": (set_score.id,)},
            {"id": "after", "source": "build", "target": "target", "gates": (gate.id,)},
        ),
        facts=(gate, set_score),
    )
    score = StateVariableIdentity("store", "score", None)
    request = _solve(
        graph,
        model,
        RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
        initial=(InitialStateValue(score, InitialValueKind.ENTRY_PRECONDITION, 2),),
    )
    result = solve_route(graph, model, request).result

    assert result is not None and result.recommended is not None
    assert result.recommended.edge_ids == ("build", "after")
    assert result.recommended.requirements[0].source is RequirementSource.PROVEN_EFFECT
    assert result.alternatives[0].requirements[0].source is RequirementSource.ENTRY_PRECONDITION


def test_exact_and_generic_shared_callee_report_the_selected_occurrence() -> None:
    graph, model = _authority(
        ("root", "callee", "after"),
        (
            {
                "id": "call-enter",
                "source": "root",
                "target": "callee",
                "kind": "call_enter",
                "call_site_id": "site-1",
            },
            {
                "id": "call-return",
                "source": "callee",
                "target": "after",
                "kind": "call_return",
                "call_site_id": "site-1",
            },
        ),
        scene_groups={
            "scene-caller": ("root",),
            "scene-shared": ("callee",),
            "scene-after": ("after",),
        },
        occurrence=("occurrence-1", "root", "callee", "call-enter"),
    )
    exact = RouteDestination(DestinationKind.EXACT_OCCURRENCE, "occurrence-1")
    generic = RouteDestination(DestinationKind.GENERIC_SCENE, "scene-shared")

    exact_result = solve_route(graph, model, _solve(graph, model, exact)).result
    generic_result = solve_route(graph, model, _solve(graph, model, generic)).result
    assert exact_result is not None and exact_result.recommended is not None
    assert generic_result is not None and generic_result.recommended is not None
    assert exact_result.recommended.selected_occurrence_id == "occurrence-1"
    assert generic_result.recommended.selected_occurrence_id == "occurrence-1"
    assert "call-enter" in exact_result.recommended.provenance.edge_ids
    assert exact_result.recommended.call_contexts[0].call_site_id == "site-1"
    assert exact_result.recommended.call_contexts[0].caller_node_id == "root"
    assert exact_result.recommended.call_contexts[0].callee_entry_node_id == "callee"
    assert exact_result.recommended.call_contexts[0].return_edge_ids == ("call-return",)


def test_multi_entry_scene_completion_uses_the_reached_narrative_anchor() -> None:
    graph, model = _authority(
        ("root", "entry-a", "entry-b"),
        ({"id": "to-b", "source": "root", "target": "entry-b"},),
        scene_groups={"scene-root": ("root",), "scene-target": ("entry-a", "entry-b")},
    )
    destination = RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target")
    result = solve_route(graph, model, _solve(graph, model, destination)).result

    assert result is not None and result.recommended is not None
    assert result.status is TechnicalStatus.CONFIRMED
    assert result.recommended.node_ids[-1] == "entry-b"


def test_resolved_call_summary_cannot_skip_ordered_callee_scenes() -> None:
    graph, model = _authority(
        ("root", "callee", "return-site", "after"),
        (
            {
                "id": "enter",
                "source": "root",
                "target": "callee",
                "kind": "call_enter",
                "call_site_id": "site",
            },
            {
                "id": "summary",
                "source": "root",
                "target": "return-site",
                "kind": "call_summary",
                "call_site_id": "site",
            },
            {
                "id": "return",
                "source": "return-site",
                "target": "after",
                "kind": "call_return",
                "call_site_id": "site",
            },
        ),
        occurrence=("occurrence", "root", "callee", "enter"),
    )
    destination = RouteDestination(DestinationKind.GENERIC_SCENE, "scene-after")
    result = solve_route(graph, model, _solve(graph, model, destination)).result

    assert result is not None and result.recommended is not None
    assert result.recommended.edge_ids == ("summary", "return")
    assert result.recommended.scene_ids == (
        "scene-root",
        "scene-callee",
        "scene-return-site",
        "scene-after",
    )
    assert result.recommended.call_contexts[0].call_edge_id == "enter"
    assert result.recommended.call_contexts[0].occurrence_id == "occurrence"
    assert result.recommended.provenance.occurrence_ids == ("occurrence",)


def test_repeatable_destination_is_complete_when_reached_once() -> None:
    graph, model = _authority(
        ("root", "event"),
        ({"id": "once", "source": "root", "target": "event"},),
        repeatable_scenes=("scene-event",),
    )
    destination = RouteDestination(DestinationKind.REPEATABLE_EVENT, "scene-event")
    result = solve_route(graph, model, _solve(graph, model, destination)).result

    assert result is not None and result.recommended is not None
    assert result.status is TechnicalStatus.CONFIRMED
    assert result.recommended.node_ids.count("event") == 1


def test_repeated_increments_cross_multiple_thresholds_without_unbounded_projection() -> None:
    gate = _fact("gate", kind="requirement", expression="score >= 3", variable="score")
    increment = _fact(
        "increment",
        kind="effect",
        expression="score += 1",
        variable="score",
        operation="increment",
        value=1,
    )
    graph, model = _authority(
        ("root", "target"),
        (
            {"id": "repeat", "source": "root", "target": "root", "effects": (increment.id,)},
            {"id": "finish", "source": "root", "target": "target", "gates": (gate.id,)},
        ),
        facts=(gate, increment),
    )
    score = StateVariableIdentity("store", "score", None)
    limits = DeterministicLimitProfile(repetition_per_transition=3)
    request = _solve(
        graph,
        model,
        RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
        initial=(InitialStateValue(score, InitialValueKind.ENTRY_PRECONDITION, 0),),
        limits=limits,
    )
    result = solve_route(graph, model, request).result

    assert result is not None and result.recommended is not None
    assert result.status is TechnicalStatus.INCOMPLETE
    assert result.termination_reason == "limit:repetition_per_transition"
    requirement = result.recommended.requirements[0]
    assert requirement.source is RequirementSource.REPEATED_EVENT
    assert requirement.repeated_count == 3
    projection = numeric_projection(graph, {"target"})
    assert projection.thresholds[score.key] == (3,)
    assert projection.key_for({score.key: 999}) == ((score.key, ">3"),)


def test_expansion_budget_replay_is_byte_identical_and_never_negative() -> None:
    graph, model = _authority(
        ("root", "middle", "target"),
        (
            {"id": "first", "source": "root", "target": "middle"},
            {"id": "second", "source": "middle", "target": "target"},
        ),
    )
    limits = DeterministicLimitProfile(expanded_states=1)
    request = _solve(
        graph,
        model,
        RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
        limits=limits,
    )
    first = solve_route(graph, model, request).result
    second = solve_route(graph, model, request).result

    assert first is not None and second is not None
    assert first.status is TechnicalStatus.INCOMPLETE
    assert first.complete is False and first.exhaustive is False
    assert first.normalized_bytes() == second.normalized_bytes()
    assert b"duration" not in first.normalized_bytes()
    assert b"timestamp" not in first.normalized_bytes()


def test_state_infeasible_requires_exhaustive_closed_world_contradiction() -> None:
    gate = _fact("gate", kind="requirement", expression="score >= 1", variable="score")
    initial_score = _fact(
        "m10-zero",
        kind="effect",
        expression="default score = 0",
        variable="score",
        operation="assignment",
        value=0,
        initialization=True,
    )
    graph, model = _authority(
        ("root", "target"),
        ({"id": "edge", "source": "root", "target": "target", "gates": (gate.id,)},),
        facts=(gate, initial_score),
        node_facts={"root": (initial_score.id,)},
    )
    score = StateVariableIdentity("store", "score", None)
    request = _solve(
        graph,
        model,
        RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
        initial=(
            InitialStateValue(
                score,
                InitialValueKind.KNOWN,
                0,
                ("evidence-m10-zero",),
            ),
        ),
    )
    result = solve_route(graph, model, request).result

    assert result is not None
    assert result.status is TechnicalStatus.STATE_INFEASIBLE
    assert result.recommended is None
    assert result.complete and result.exhaustive and result.closed_world
    assert result.diagnostics == ("exact supported contradiction",)
    assert result.negative_provenance is not None
    assert result.negative_provenance.fact_ids == (gate.id,)


def test_dynamic_transfer_withholds_no_route_and_marks_best_known_instructions() -> None:
    graph, model = _authority(
        ("root", "target"),
        (
            {
                "id": "dynamic",
                "source": "root",
                "target": "target",
                "kind": "unresolved",
                "resolved": False,
            },
        ),
        node_kinds={"root": CanonicalNodeKind.CHOICE},
    )
    destination = RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target")
    first = solve_route(graph, model, _solve(graph, model, destination)).result
    second = solve_route(graph, model, _solve(graph, model, destination)).result

    assert first is not None and first.recommended is not None and second is not None
    assert first.status is TechnicalStatus.BEST_KNOWN
    assert first.closed_world is False
    assert first.recommended.instructions == second.recommended.instructions  # type: ignore[union-attr]
    assert [item.kind for item in first.recommended.instructions] == [
        "scene",
        "scene",
        "choice",
        "warning",
    ]
    assert all(item.text for item in first.recommended.instructions)


def test_unrelated_contradiction_cannot_make_exact_occurrence_state_infeasible() -> None:
    unrelated_gate = _fact(
        "unrelated-gate",
        kind="requirement",
        expression="score >= 1",
        variable="score",
    )
    graph, model = _authority(
        ("root", "other", "callee", "bad"),
        (
            {
                "id": "wrong-call",
                "source": "root",
                "target": "callee",
                "kind": "call_enter",
                "call_site_id": "wrong-site",
            },
            {
                "id": "right-call",
                "source": "other",
                "target": "callee",
                "kind": "call_enter",
                "call_site_id": "right-site",
            },
            {
                "id": "unrelated",
                "source": "root",
                "target": "bad",
                "gates": (unrelated_gate.id,),
            },
        ),
        facts=(unrelated_gate,),
        occurrence=("occurrence-right", "other", "callee", "right-call"),
    )
    score = StateVariableIdentity("store", "score", None)
    request = _solve(
        graph,
        model,
        RouteDestination(DestinationKind.EXACT_OCCURRENCE, "occurrence-right"),
        initial=(InitialStateValue(score, InitialValueKind.ENTRY_PRECONDITION, 0),),
    )
    result = solve_route(graph, model, request).result

    assert result is not None
    assert result.status is TechnicalStatus.NO_STATIC_ROUTE
    assert result.status is not TechnicalStatus.STATE_INFEASIBLE


def test_cancellation_publishes_no_normalized_result() -> None:
    graph, model = _authority(
        ("root", "target"),
        ({"id": "edge", "source": "root", "target": "target"},),
    )
    destination = RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target")
    attempt = solve_route(
        graph,
        model,
        _solve(graph, model, destination),
        cancelled=lambda: True,
    )

    assert attempt.cancelled is True
    assert attempt.result is None
