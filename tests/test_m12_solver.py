from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

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
    RouteResult,
    StateVariableIdentity,
    TechnicalStatus,
)
from renpy_story_mapper.m12_persistence import normalized_result_bytes
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
        reachability = spec.get("reachability")
        if reachability is not None and not isinstance(reachability, ReachabilityStatus):
            raise TypeError("synthetic edge reachability must use ReachabilityStatus")
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
                reachability
                or (
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

    automatic_request = _solve(graph, model, destination)
    assert automatic_request.initial_state == known_request.initial_state
    automatic_result = solve_route(graph, model, automatic_request).result
    assert automatic_result is not None
    assert automatic_result.status is TechnicalStatus.CONFIRMED

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

    persistent_gate = _fact(
        "persistent-gate",
        kind="requirement",
        expression="persistent.score >= 2",
        variable="persistent.score",
    )
    persistent_default = _fact(
        "persistent-default",
        kind="effect",
        expression="default persistent.score = 2",
        variable="persistent.score",
        operation="assignment",
        value=2,
        initialization=True,
    )
    persistent_graph, persistent_model = _authority(
        ("root", "target"),
        (
            {
                "id": "persistent-edge",
                "source": "root",
                "target": "target",
                "gates": (persistent_gate.id,),
            },
        ),
        facts=(persistent_gate, persistent_default),
        node_facts={"root": (persistent_default.id,)},
    )
    persistent_request = _solve(persistent_graph, persistent_model, destination)
    assert persistent_request.initial_state == ()
    persistent_default_result = solve_route(
        persistent_graph, persistent_model, persistent_request
    ).result
    assert persistent_default_result is not None
    assert persistent_default_result.status is TechnicalStatus.BEST_KNOWN


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

    persistent_fact = _fact(
        "persistent-init",
        kind="effect",
        expression="default persistent.score = 2",
        variable="persistent.score",
        operation="assignment",
        value=2,
        initialization=True,
    )
    persistent_graph, persistent_model = _authority(
        ("root", "target"),
        ({"id": "edge", "source": "root", "target": "target"},),
        facts=(persistent_fact,),
        node_facts={"root": (persistent_fact.id,)},
    )
    with pytest.raises(ValueError, match="lacks exact M10 initialization proof"):
        _solve(
            persistent_graph,
            persistent_model,
            RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
            initial=(
                InitialStateValue(
                    StateVariableIdentity("persistent", "score", True),
                    InitialValueKind.KNOWN,
                    2,
                    ("evidence-persistent-init",),
                ),
            ),
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
    effect_claim = result.recommended.satisfying_effect_claims[0]
    effect_requirement = next(
        item
        for item in result.recommended.requirements
        if item.source is RequirementSource.PROVEN_EFFECT
    )
    assert effect_claim.fact_id == set_a.id
    assert effect_claim.evidence_ids == ("evidence-set-a",)
    assert effect_claim.evidence_ids != effect_requirement.evidence_ids
    assert set_a.id in result.recommended.provenance.fact_ids


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


def test_mixed_entry_value_and_internal_increment_remains_an_entry_precondition() -> None:
    gate = _fact("mixed-gate", kind="requirement", expression="score >= 2", variable="score")
    increment = _fact(
        "mixed-increment",
        kind="effect",
        expression="score += 1",
        variable="score",
        operation="increment",
        value=1,
    )
    graph, model = _authority(
        ("root", "build", "target"),
        (
            {
                "id": "mixed-build",
                "source": "root",
                "target": "build",
                "effects": (increment.id,),
            },
            {
                "id": "mixed-finish",
                "source": "build",
                "target": "target",
                "gates": (gate.id,),
            },
        ),
        facts=(gate, increment),
    )
    score = StateVariableIdentity("store", "score", None)
    request = _solve(
        graph,
        model,
        RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
        initial=(InitialStateValue(score, InitialValueKind.ENTRY_PRECONDITION, 1),),
    )

    result = solve_route(graph, model, request).result

    assert result is not None and result.recommended is not None
    assert result.status is TechnicalStatus.PREREQUISITES
    requirement = result.recommended.requirements[0]
    assert requirement.source is RequirementSource.ENTRY_PRECONDITION
    assert requirement.entry_precondition == request.initial_state[0]
    assert requirement.supporting_effect_ids == (increment.id,)
    assert result.recommended.satisfying_effect_claims[0].fact_id == increment.id
    assert {gate.id, increment.id} <= set(result.recommended.provenance.fact_ids)
    assert any(
        instruction.kind == "starting_assumption"
        and instruction.text == "Start with store:score:persistent-unknown = 1."
        for instruction in result.recommended.instructions
    )


def test_mixed_entry_value_keeps_repeated_contributing_effect_count() -> None:
    gate = _fact("mixed-repeat-gate", kind="requirement", expression="score >= 2", variable="score")
    increment = _fact(
        "mixed-repeat-increment",
        kind="effect",
        expression="score += 1",
        variable="score",
        operation="increment",
        value=1,
    )
    graph, model = _authority(
        ("root", "first", "second", "target"),
        (
            {
                "id": "mixed-repeat-first",
                "source": "root",
                "target": "first",
                "effects": (increment.id,),
            },
            {
                "id": "mixed-repeat-second",
                "source": "first",
                "target": "second",
                "effects": (increment.id,),
            },
            {
                "id": "mixed-repeat-finish",
                "source": "second",
                "target": "target",
                "gates": (gate.id,),
            },
        ),
        facts=(gate, increment),
    )
    score = StateVariableIdentity("store", "score", None)
    request = _solve(
        graph,
        model,
        RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
        initial=(InitialStateValue(score, InitialValueKind.ENTRY_PRECONDITION, 0),),
    )

    result = solve_route(graph, model, request).result

    assert result is not None and result.recommended is not None
    assert result.status is TechnicalStatus.PREREQUISITES
    requirement = result.recommended.requirements[0]
    assert requirement.source is RequirementSource.ENTRY_PRECONDITION
    assert requirement.entry_precondition == request.initial_state[0]
    assert requirement.supporting_effect_counts == ((increment.id, 2),)
    repeat = next(
        claim
        for claim in result.recommended.repeated_action_claims
        if claim.fact_id == increment.id
    )
    assert repeat.repeated_count == 2
    assert any(
        instruction.kind == "repeat" and instruction.fact_id == increment.id
        for instruction in result.recommended.instructions
    )


def test_fully_internal_score_outranks_mixed_entry_and_effect_score() -> None:
    gate = _fact("mixed-rank-gate", kind="requirement", expression="score >= 2", variable="score")
    increment = _fact(
        "mixed-rank-increment",
        kind="effect",
        expression="score += 1",
        variable="score",
        operation="increment",
        value=1,
    )
    assignment = _fact(
        "mixed-rank-assignment",
        kind="effect",
        expression="score = 2",
        variable="score",
        operation="assignment",
        value=2,
    )
    graph, model = _authority(
        ("root", "join", "target"),
        (
            {
                "id": "mixed-path",
                "source": "root",
                "target": "join",
                "effects": (increment.id,),
            },
            {
                "id": "internal-path",
                "source": "root",
                "target": "join",
                "effects": (assignment.id,),
            },
            {
                "id": "gate-edge",
                "source": "join",
                "target": "target",
                "gates": (gate.id,),
            },
        ),
        facts=(gate, increment, assignment),
    )
    score = StateVariableIdentity("store", "score", None)
    result = solve_route(
        graph,
        model,
        _solve(
            graph,
            model,
            RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
            initial=(InitialStateValue(score, InitialValueKind.ENTRY_PRECONDITION, 1),),
        ),
    ).result

    assert result is not None and result.recommended is not None
    assert result.recommended.edge_ids == ("internal-path", "gate-edge")
    assert result.recommended.requirements[0].source is RequirementSource.PROVEN_EFFECT
    mixed = next(item for item in result.alternatives if item.edge_ids[0] == "mixed-path")
    assert mixed.requirements[0].source is RequirementSource.ENTRY_PRECONDITION
    assert mixed.requirements[0].supporting_effect_ids == (increment.id,)


def test_later_effect_cannot_erase_an_earlier_entry_requirement() -> None:
    gate = _fact(
        "chronology-entry-gate",
        kind="requirement",
        expression="score >= 2",
        variable="score",
    )
    assignment = _fact(
        "chronology-entry-assignment",
        kind="effect",
        expression="score = 2",
        variable="score",
        operation="assignment",
        value=2,
    )
    graph, model = _authority(
        ("root", "first", "second", "target"),
        (
            {
                "id": "entry-first-gate",
                "source": "root",
                "target": "first",
                "gates": (gate.id,),
            },
            {
                "id": "entry-later-effect",
                "source": "first",
                "target": "second",
                "effects": (assignment.id,),
            },
            {
                "id": "entry-second-gate",
                "source": "second",
                "target": "target",
                "gates": (gate.id,),
            },
        ),
        facts=(gate, assignment),
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
    assert result.status is TechnicalStatus.PREREQUISITES
    assert result.recommended.requirements[0].source is RequirementSource.ENTRY_PRECONDITION
    assert result.recommended.requirements[0].entry_precondition == request.initial_state[0]


def test_later_effect_cannot_erase_an_earlier_unknown_requirement() -> None:
    gate = _fact(
        "chronology-unknown-gate",
        kind="requirement",
        expression="score >= 2",
        variable="score",
    )
    assignment = _fact(
        "chronology-unknown-assignment",
        kind="effect",
        expression="score = 2",
        variable="score",
        operation="assignment",
        value=2,
    )
    graph, model = _authority(
        ("root", "first", "second", "target"),
        (
            {
                "id": "unknown-first-gate",
                "source": "root",
                "target": "first",
                "gates": (gate.id,),
            },
            {
                "id": "unknown-later-effect",
                "source": "first",
                "target": "second",
                "effects": (assignment.id,),
            },
            {
                "id": "unknown-second-gate",
                "source": "second",
                "target": "target",
                "gates": (gate.id,),
            },
        ),
        facts=(gate, assignment),
    )
    score = StateVariableIdentity("store", "score", None)
    result = solve_route(
        graph,
        model,
        _solve(
            graph,
            model,
            RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
            initial=(InitialStateValue(score, InitialValueKind.UNKNOWN),),
        ),
    ).result

    assert result is not None and result.recommended is not None
    assert result.status is TechnicalStatus.BEST_KNOWN
    assert result.recommended.requirements[0].source is RequirementSource.UNKNOWN


def test_revisited_gate_retains_entry_requirement_after_possible_write() -> None:
    gate = _fact(
        "chronology-revisited-gate",
        kind="requirement",
        expression="score >= 2",
        variable="score",
    )
    possible_write = _fact(
        "chronology-possible-write",
        kind="effect",
        expression="score = dynamic_value",
        variable="score",
        operation="assignment",
        value=0,
        status="possible",
    )
    graph, model = _authority(
        ("root", "first", "second", "target"),
        (
            {
                "id": "revisited-first-gate",
                "source": "root",
                "target": "first",
                "gates": (gate.id,),
            },
            {
                "id": "revisited-possible-write",
                "source": "first",
                "target": "second",
                "effects": (possible_write.id,),
            },
            {
                "id": "revisited-second-gate",
                "source": "second",
                "target": "target",
                "gates": (gate.id,),
            },
        ),
        facts=(gate, possible_write),
    )
    score = StateVariableIdentity("store", "score", None)
    entry = InitialStateValue(score, InitialValueKind.ENTRY_PRECONDITION, 2)

    result = solve_route(
        graph,
        model,
        _solve(
            graph,
            model,
            RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
            initial=(entry,),
        ),
    ).result

    assert result is not None and result.recommended is not None
    assert result.status is TechnicalStatus.BEST_KNOWN
    assert [item.source for item in result.recommended.requirements] == [
        RequirementSource.ENTRY_PRECONDITION,
        RequirementSource.UNKNOWN,
    ]
    assert result.recommended.requirements[0].entry_precondition == entry
    assert result.recommended.ranking_key[1:3] == (1, 1)
    assert any(
        instruction.kind == "starting_assumption"
        and instruction.text == "Start with store:score:persistent-unknown = 2."
        for instruction in result.recommended.instructions
    )


def test_revisited_gate_counts_one_external_assumption_as_effects_accumulate() -> None:
    gate = _fact(
        "chronology-accumulating-gate",
        kind="requirement",
        expression="score >= 1",
        variable="score",
    )
    increment = _fact(
        "chronology-accumulating-increment",
        kind="effect",
        expression="score += 1",
        variable="score",
        operation="increment",
        value=1,
    )
    flag_gate = _fact(
        "chronology-flag-gate",
        kind="requirement",
        expression="flag == 1",
        variable="flag",
    )
    graph, model = _authority(
        ("root", "first", "second", "detour1", "detour2", "detour3", "target"),
        (
            {
                "id": "accumulating-first-effect",
                "source": "root",
                "target": "first",
                "effects": (increment.id,),
            },
            {
                "id": "accumulating-first-gate",
                "source": "first",
                "target": "second",
                "gates": (gate.id,),
                "effects": (increment.id,),
            },
            {
                "id": "accumulating-second-gate",
                "source": "second",
                "target": "target",
                "gates": (gate.id,),
            },
            {
                "id": "detour-start",
                "source": "root",
                "target": "detour1",
            },
            {
                "id": "detour-middle",
                "source": "detour1",
                "target": "detour2",
            },
            {
                "id": "detour-end",
                "source": "detour2",
                "target": "detour3",
            },
            {
                "id": "detour-gate",
                "source": "detour3",
                "target": "target",
                "gates": (flag_gate.id,),
            },
        ),
        facts=(gate, increment, flag_gate),
    )
    score = StateVariableIdentity("store", "score", None)
    flag = StateVariableIdentity("store", "flag", None)
    score_entry = InitialStateValue(score, InitialValueKind.ENTRY_PRECONDITION, 0)
    flag_entry = InitialStateValue(flag, InitialValueKind.ENTRY_PRECONDITION, 1)

    result = solve_route(
        graph,
        model,
        _solve(
            graph,
            model,
            RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
            initial=(score_entry, flag_entry),
        ),
    ).result

    assert result is not None and result.recommended is not None
    route = result.recommended
    assert result.status is TechnicalStatus.PREREQUISITES
    assert route.edge_ids[0] == "accumulating-first-effect"
    assert [item.supporting_effect_counts for item in route.requirements] == [
        ((increment.id, 1),),
        ((increment.id, 2),),
    ]
    assert route.ranking_key[2] == 1
    assert sum(item.kind == "starting_assumption" for item in route.instructions) == 1
    assert len(route.satisfying_effect_claims) == 1
    assert route.repeated_action_claims[-1].repeated_count == 2


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
        ("root", "callee", "callee-exit", "return-site", "after"),
        (
            {
                "id": "enter",
                "source": "root",
                "target": "callee",
                "kind": "call_enter",
                "call_site_id": "site",
            },
            {
                "id": "callee-return",
                "source": "callee",
                "target": "callee-exit",
                "kind": "call_return",
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
        scene_groups={
            "scene-root": ("root",),
            "scene-callee": ("callee", "callee-exit"),
            "scene-return-site": ("return-site",),
            "scene-after": ("after",),
        },
        occurrence=("occurrence", "root", "callee", "enter"),
    )
    destination = RouteDestination(DestinationKind.GENERIC_SCENE, "scene-after")
    result = solve_route(graph, model, _solve(graph, model, destination)).result

    assert result is not None and result.recommended is not None
    assert result.recommended.edge_ids == (
        "enter",
        "callee-return",
        "summary",
        "return",
    )
    assert result.recommended.scene_ids == (
        "scene-root",
        "scene-callee",
        "scene-return-site",
        "scene-after",
    )
    assert result.recommended.call_contexts[0].call_edge_id == "enter"
    assert result.recommended.call_contexts[0].occurrence_id == "occurrence"
    assert result.recommended.provenance.occurrence_ids == ("occurrence",)
    assert "callee" in result.recommended.provenance.node_ids


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
    assert requirement.source is RequirementSource.ENTRY_PRECONDITION
    assert requirement.entry_precondition == request.initial_state[0]
    assert requirement.supporting_effect_ids == (increment.id,)
    assert requirement.repeated_count is None
    assert result.recommended.repeated_action_claims
    repeat_claim = result.recommended.repeated_action_claims[0]
    assert repeat_claim.edge_id == "repeat"
    assert repeat_claim.repeated_count == 2
    assert repeat_claim.evidence_ids or repeat_claim.proof_ids
    projection = numeric_projection(graph, {"target"})
    assert projection.thresholds[score.key] == (3,)
    assert projection.key_for({score.key: 999}) == ((score.key, ">3"),)


def test_one_increment_after_initialization_is_a_proven_effect_not_a_repeat() -> None:
    gate = _fact("gate", kind="requirement", expression="score >= 1", variable="score")
    initial_score = _fact(
        "initial-score",
        kind="effect",
        expression="default score = 0",
        variable="score",
        operation="assignment",
        value=0,
        initialization=True,
    )
    increment = _fact(
        "increment",
        kind="effect",
        expression="score += 1",
        variable="score",
        operation="increment",
        value=1,
    )
    graph, model = _authority(
        ("root", "built", "target"),
        (
            {
                "id": "build-once",
                "source": "root",
                "target": "built",
                "effects": (increment.id,),
            },
            {
                "id": "finish",
                "source": "built",
                "target": "target",
                "gates": (gate.id,),
            },
        ),
        facts=(gate, initial_score, increment),
        node_facts={"root": (initial_score.id,)},
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
    requirement = result.recommended.requirements[0]
    assert requirement.source is RequirementSource.PROVEN_EFFECT
    assert requirement.satisfying_effect_id == increment.id
    assert requirement.repeated_count is None
    assert result.recommended.repeated_action_claims == ()


def test_repeated_effect_across_distinct_edges_keeps_exact_effect_provenance() -> None:
    gate = _fact("repeat-gate", kind="requirement", expression="score >= 2", variable="score")
    initial_score = _fact(
        "repeat-initial",
        kind="effect",
        expression="default score = 0",
        variable="score",
        operation="assignment",
        value=0,
        initialization=True,
    )
    increment = _fact(
        "repeat-increment",
        kind="effect",
        expression="score += 1",
        variable="score",
        operation="increment",
        value=1,
    )
    graph, model = _authority(
        ("root", "first", "second", "target"),
        (
            {"id": "first-build", "source": "root", "target": "first", "effects": (increment.id,)},
            {
                "id": "second-build",
                "source": "first",
                "target": "second",
                "effects": (increment.id,),
            },
            {"id": "finish", "source": "second", "target": "target", "gates": (gate.id,)},
        ),
        facts=(gate, initial_score, increment),
        node_facts={"root": (initial_score.id,)},
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
    requirement = result.recommended.requirements[0]
    assert requirement.source is RequirementSource.REPEATED_EVENT
    assert requirement.repeated_count == 2
    assert requirement.repeated_effect_id == increment.id
    assert requirement.supporting_effect_ids == (initial_score.id, increment.id)
    assert {claim.fact_id for claim in result.recommended.satisfying_effect_claims} == {
        initial_score.id,
        increment.id,
    }
    assert result.recommended.repeated_action_claims[0].fact_id == increment.id
    assert result.recommended.repeated_action_claims[0].repeated_count == 2
    assert {gate.id, initial_score.id, increment.id} <= set(
        result.recommended.provenance.fact_ids
    )
    assert any(
        instruction.kind == "repeat" and instruction.fact_id == increment.id
        for instruction in result.recommended.instructions
    )


def test_distinct_accumulated_effects_keep_the_complete_support_chain() -> None:
    gate = _fact("chain-gate", kind="requirement", expression="score >= 2", variable="score")
    initial_score = _fact(
        "chain-initial",
        kind="effect",
        expression="default score = 0",
        variable="score",
        operation="assignment",
        value=0,
        initialization=True,
    )
    first_increment = _fact(
        "chain-first",
        kind="effect",
        expression="score += 1",
        variable="score",
        operation="increment",
        value=1,
    )
    second_increment = _fact(
        "chain-second",
        kind="effect",
        expression="score += 1",
        variable="score",
        operation="increment",
        value=1,
    )
    graph, model = _authority(
        ("root", "first", "second", "target"),
        (
            {
                "id": "first-build",
                "source": "root",
                "target": "first",
                "effects": (first_increment.id,),
            },
            {
                "id": "second-build",
                "source": "first",
                "target": "second",
                "effects": (second_increment.id,),
            },
            {"id": "finish", "source": "second", "target": "target", "gates": (gate.id,)},
        ),
        facts=(gate, initial_score, first_increment, second_increment),
        node_facts={"root": (initial_score.id,)},
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
    requirement = result.recommended.requirements[0]
    assert requirement.source is RequirementSource.PROVEN_EFFECT
    assert requirement.satisfying_effect_id == second_increment.id
    assert requirement.supporting_effect_ids == (
        initial_score.id,
        first_increment.id,
        second_increment.id,
    )
    assert {claim.fact_id for claim in result.recommended.satisfying_effect_claims} == {
        initial_score.id,
        first_increment.id,
        second_increment.id,
    }
    assert {gate.id, initial_score.id, first_increment.id, second_increment.id} <= set(
        result.recommended.provenance.fact_ids
    )


def test_call_resume_projection_preserves_internal_gate_and_effect_semantics() -> None:
    gate = _fact("callee-gate", kind="requirement", expression="flag == True", variable="flag")
    initial_flag = _fact(
        "initial-flag",
        kind="effect",
        expression="default flag = False",
        variable="flag",
        operation="assignment",
        value=False,
        initialization=True,
    )
    set_flag = _fact(
        "set-flag",
        kind="effect",
        expression="flag = True",
        variable="flag",
        operation="assignment",
        value=True,
    )
    base_edges = (
        {
            "id": "enter",
            "source": "root",
            "target": "callee",
            "kind": "call_enter",
            "call_site_id": "site",
        },
        {
            "id": "internal-gate",
            "source": "callee",
            "target": "callee-return",
            "gates": (gate.id,),
        },
        {
            "id": "procedure-return",
            "source": "callee-return",
            "target": "callee-exit",
            "kind": "call_return",
        },
        {
            "id": "summary",
            "source": "root",
            "target": "return-site",
            "kind": "call_summary",
            "call_site_id": "site",
        },
        {
            "id": "resume",
            "source": "return-site",
            "target": "target",
            "kind": "call_return",
            "call_site_id": "site",
        },
    )
    nodes = ("root", "callee", "callee-return", "callee-exit", "return-site", "target")
    graph, model = _authority(
        nodes,
        base_edges,
        facts=(gate, initial_flag, set_flag),
        node_facts={"root": (initial_flag.id,)},
    )
    destination = RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target")
    contradiction = solve_route(graph, model, _solve(graph, model, destination)).result

    assert contradiction is not None
    assert contradiction.status is TechnicalStatus.STATE_INFEASIBLE
    assert contradiction.negative_provenance is not None
    assert contradiction.negative_provenance.fact_ids == (gate.id, initial_flag.id)

    effect_edges = (dict(base_edges[0], effects=(set_flag.id,)), *base_edges[1:])
    effect_graph, effect_model = _authority(
        nodes,
        effect_edges,
        facts=(gate, initial_flag, set_flag),
        node_facts={"root": (initial_flag.id,)},
    )
    solved = solve_route(
        effect_graph,
        effect_model,
        _solve(effect_graph, effect_model, destination),
    ).result
    assert solved is not None and solved.recommended is not None
    assert solved.status is TechnicalStatus.CONFIRMED
    assert solved.recommended.requirements[0].satisfying_effect_id == set_flag.id


def test_target_cone_ignores_irrelevant_cycle_without_downgrading_route() -> None:
    graph, model = _authority(
        ("root", "target", "unrelated-a", "unrelated-b"),
        (
            {"id": "direct", "source": "root", "target": "target"},
            {"id": "stray", "source": "root", "target": "unrelated-a"},
            {"id": "cycle-a", "source": "unrelated-a", "target": "unrelated-b"},
            {"id": "cycle-b", "source": "unrelated-b", "target": "unrelated-a"},
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
    assert result.status is TechnicalStatus.CONFIRMED
    assert result.recommended.edge_ids == ("direct",)
    assert result.budget_usage.limiting_dimension is None


def test_sequential_diamonds_retain_bounded_alternatives_without_cartesian_search() -> None:
    depth = 12
    nodes = ["root"]
    edges: list[dict[str, object]] = []
    choice_nodes = {"root": CanonicalNodeKind.CHOICE}
    source = "root"
    for index in range(depth):
        left = f"left-{index}"
        right = f"right-{index}"
        merge = f"merge-{index}"
        nodes.extend((left, right, merge))
        edges.extend(
            (
                {"id": f"choose-left-{index}", "source": source, "target": left},
                {"id": f"choose-right-{index}", "source": source, "target": right},
                {"id": f"merge-left-{index}", "source": left, "target": merge},
                {"id": f"merge-right-{index}", "source": right, "target": merge},
            )
        )
        choice_nodes[merge] = CanonicalNodeKind.CHOICE
        source = merge
    nodes.append("target")
    edges.append({"id": "finish", "source": source, "target": "target"})
    graph, model = _authority(tuple(nodes), tuple(edges), node_kinds=choice_nodes)
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
    assert result.status is TechnicalStatus.INCOMPLETE
    assert result.termination_reason == "limit:alternatives"
    assert result.budget_usage.expanded_states < 250
    assert len(result.alternatives) == 3


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
    assert result.termination_reason == "exhaustive"
    assert result.diagnostics == ("exact supported contradiction",)
    assert result.negative_provenance is not None
    assert result.negative_provenance.fact_ids == (gate.id, initial_score.id)
    assert normalized_result_bytes(result.normalized_dict()) == result.normalized_bytes()
    with pytest.raises(ValueError, match="exhaustive closed-world"):
        replace(
            result,
            exhaustive=False,
            termination_reason="best_route_proven",
        )


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


def test_generic_shared_scene_keeps_open_direct_context_beside_gated_occurrence() -> None:
    gate = _fact("call-gate", kind="requirement", expression="score >= 1", variable="score")
    graph, model = _authority(
        ("root", "caller", "shared"),
        (
            {"id": "direct", "source": "root", "target": "shared"},
            {"id": "to-caller", "source": "root", "target": "caller"},
            {
                "id": "gated-call",
                "source": "caller",
                "target": "shared",
                "kind": "call_enter",
                "call_site_id": "gated-site",
                "gates": (gate.id,),
            },
        ),
        facts=(gate,),
        scene_groups={
            "scene-root": ("root",),
            "scene-caller": ("caller",),
            "scene-shared": ("shared",),
        },
        occurrence=("gated-occurrence", "caller", "shared", "gated-call"),
    )
    score = StateVariableIdentity("store", "score", None)
    result = solve_route(
        graph,
        model,
        _solve(
            graph,
            model,
            RouteDestination(DestinationKind.GENERIC_SCENE, "scene-shared"),
            initial=(InitialStateValue(score, InitialValueKind.ENTRY_PRECONDITION, 0),),
        ),
    ).result

    assert result is not None and result.recommended is not None
    assert result.recommended.edge_ids == ("direct",)
    assert result.status is not TechnicalStatus.STATE_INFEASIBLE


@pytest.mark.parametrize(
    "reachability",
    (
        ReachabilityStatus.REACHABLE_UNDER_INFERRED_REQUIREMENTS,
        ReachabilityStatus.POSSIBLY_DEAD,
        ReachabilityStatus.UNREACHABLE_IN_RESOLVED_STATIC_GRAPH,
    ),
)
def test_non_proven_m10_reachability_never_becomes_confirmed(
    reachability: ReachabilityStatus,
) -> None:
    graph, model = _authority(
        ("root", "target"),
        (
            {
                "id": "uncertain-edge",
                "source": "root",
                "target": "target",
                "reachability": reachability,
            },
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
    assert result.status is TechnicalStatus.BEST_KNOWN
    assert result.recommended.uncertainty_claims
    claim = result.recommended.uncertainty_claims[0]
    assert claim.edge_id == "uncertain-edge"
    assert claim.evidence_ids


def test_merged_material_prefixes_survive_dominance_as_alternatives() -> None:
    graph, model = _authority(
        ("root", "left", "right", "merge", "target"),
        (
            {"id": "choose-left", "source": "root", "target": "left"},
            {"id": "choose-right", "source": "root", "target": "right"},
            {"id": "left-merge", "source": "left", "target": "merge"},
            {"id": "right-merge", "source": "right", "target": "merge"},
            {"id": "finish", "source": "merge", "target": "target"},
        ),
        node_kinds={"root": CanonicalNodeKind.CHOICE},
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
    paths = {result.recommended.edge_ids, *(item.edge_ids for item in result.alternatives)}
    assert any("choose-left" in path for path in paths)
    assert any("choose-right" in path for path in paths)


def test_each_material_claim_carries_an_exact_expandable_source() -> None:
    graph, model = _authority(
        ("root", "target"),
        ({"id": "choice", "source": "root", "target": "target"},),
        node_kinds={"root": CanonicalNodeKind.CHOICE},
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
    assert result.recommended.visible_choice_claims
    for claim in result.recommended.visible_choice_claims:
        assert claim.edge_id and (claim.evidence_ids or claim.proof_ids)
    for instruction in result.recommended.instructions:
        assert any(
            (
                instruction.scene_id,
                instruction.edge_id,
                instruction.fact_id,
                instruction.lane_id,
                instruction.node_id,
            )
        )
        assert instruction.evidence_ids or instruction.proof_ids


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


def _solve_two_supported_gates(
    first: CanonicalFact,
    second: CanonicalFact,
    *,
    first_effects: Sequence[str] = (),
    limits: DeterministicLimitProfile | None = None,
) -> tuple[CanonicalGraph, RouteResult]:
    facts: list[CanonicalFact] = [first, second]
    if first_effects:
        effect_by_id = {
            "set-x-false": _fact(
                "set-x-false",
                kind="effect",
                expression="x = False",
                variable="x",
                operation="assignment",
                value=False,
            )
        }
        facts.extend(effect_by_id[item] for item in first_effects)
    graph, model = _authority(
        ("root", "middle", "target"),
        (
            {
                "id": "first-gate",
                "source": "root",
                "target": "middle",
                "gates": (first.id,),
                "effects": tuple(first_effects),
            },
            {
                "id": "second-gate",
                "source": "middle",
                "target": "target",
                "gates": (second.id,),
            },
        ),
        facts=tuple(facts),
    )
    result = solve_route(
        graph,
        model,
        _solve(
            graph,
            model,
            RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
            limits=limits,
        ),
    ).result
    assert result is not None
    return graph, result


def test_supported_boolean_truth_then_falsity_is_pruned() -> None:
    truth = _fact("truth", kind="requirement", expression="x", variable="x")
    falsity = _fact("falsity", kind="requirement", expression="not x", variable="x")

    _, result = _solve_two_supported_gates(truth, falsity)

    assert result.status is TechnicalStatus.STATE_INFEASIBLE
    assert result.recommended is None
    assert result.negative_provenance is not None
    assert result.negative_provenance.fact_ids == ("falsity", "truth")


def test_supported_numeric_lower_and_upper_contradiction_is_pruned() -> None:
    lower = _fact(
        "lower",
        kind="requirement",
        expression="score >= 5",
        variable="score",
    )
    upper = _fact(
        "upper",
        kind="requirement",
        expression="score < 5",
        variable="score",
    )

    _, result = _solve_two_supported_gates(lower, upper)

    assert result.status is TechnicalStatus.STATE_INFEASIBLE
    assert result.negative_provenance is not None
    assert result.negative_provenance.fact_ids == ("lower", "upper")


def test_compatible_numeric_interval_remains_a_best_known_route() -> None:
    lower = _fact(
        "lower",
        kind="requirement",
        expression="score >= 5",
        variable="score",
    )
    upper = _fact(
        "upper",
        kind="requirement",
        expression="score < 10",
        variable="score",
    )

    _, result = _solve_two_supported_gates(lower, upper)

    assert result.status is TechnicalStatus.BEST_KNOWN
    assert result.recommended is not None
    assert result.recommended.edge_ids == ("first-gate", "second-gate")


def test_conflicting_categorical_equalities_are_pruned() -> None:
    first = _fact(
        "route-a",
        kind="requirement",
        expression='route == "a"',
        variable="route",
    )
    second = _fact(
        "route-b",
        kind="requirement",
        expression='route == "b"',
        variable="route",
    )

    _, result = _solve_two_supported_gates(first, second)

    assert result.status is TechnicalStatus.STATE_INFEASIBLE
    assert result.negative_provenance is not None
    assert result.negative_provenance.fact_ids == ("route-a", "route-b")


def test_literal_equality_and_exclusion_contradiction_is_pruned() -> None:
    equality = _fact(
        "route-a",
        kind="requirement",
        expression='route == "a"',
        variable="route",
    )
    exclusion = _fact(
        "not-route-a",
        kind="requirement",
        expression='route != "a"',
        variable="route",
    )

    _, result = _solve_two_supported_gates(equality, exclusion)

    assert result.status is TechnicalStatus.STATE_INFEASIBLE
    assert result.negative_provenance is not None
    assert result.negative_provenance.fact_ids == ("not-route-a", "route-a")


def test_proven_intervening_effect_replaces_the_prior_constraint() -> None:
    truth = _fact("truth", kind="requirement", expression="x", variable="x")
    falsity = _fact("falsity", kind="requirement", expression="not x", variable="x")

    _, result = _solve_two_supported_gates(
        truth,
        falsity,
        first_effects=("set-x-false",),
    )

    assert result.status is TechnicalStatus.BEST_KNOWN
    assert result.recommended is not None
    assert result.recommended.edge_ids == ("first-gate", "second-gate")
    assert result.recommended.requirements[-1].satisfying_effect_id == "set-x-false"


def test_unsupported_creator_expression_stays_unknown_not_contradictory() -> None:
    creator = _fact(
        "creator",
        kind="requirement",
        expression="creator_check(x)",
        variable="x",
    )
    falsity = _fact("falsity", kind="requirement", expression="not x", variable="x")

    _, result = _solve_two_supported_gates(creator, falsity)

    assert result.status is TechnicalStatus.BEST_KNOWN
    assert result.recommended is not None
    assert any("creator_check" in item for item in result.recommended.uncertainty_warnings)


def test_accumulated_state_infeasible_requires_exhaustive_closed_world_completion() -> None:
    truth = _fact("truth", kind="requirement", expression="x", variable="x")
    falsity = _fact("falsity", kind="requirement", expression="not x", variable="x")

    _, bounded = _solve_two_supported_gates(
        truth,
        falsity,
        limits=DeterministicLimitProfile(expanded_states=1),
    )
    _, exhaustive = _solve_two_supported_gates(truth, falsity)

    assert bounded.status is TechnicalStatus.INCOMPLETE
    assert bounded.exhaustive is False
    assert exhaustive.status is TechnicalStatus.STATE_INFEASIBLE
    assert exhaustive.complete and exhaustive.exhaustive and exhaustive.closed_world


def test_at_least_forty_sequential_calls_do_not_accumulate_completed_frames() -> None:
    call_count = 40
    nodes = ["root"]
    edges: list[dict[str, object]] = []
    caller = "root"
    for index in range(call_count):
        callee = f"callee-{index}"
        callee_exit = f"callee-exit-{index}"
        return_site = f"return-site-{index}"
        continuation = f"caller-{index + 1}" if index + 1 < call_count else "target"
        nodes.extend((callee, callee_exit, return_site, continuation))
        site = f"site-{index}"
        edges.extend(
            (
                {
                    "id": f"enter-{index}",
                    "source": caller,
                    "target": callee,
                    "kind": "call_enter",
                    "call_site_id": site,
                },
                {
                    "id": f"procedure-return-{index}",
                    "source": callee,
                    "target": callee_exit,
                    "kind": "call_return",
                },
                {
                    "id": f"summary-{index}",
                    "source": caller,
                    "target": return_site,
                    "kind": "call_summary",
                    "call_site_id": site,
                },
                {
                    "id": f"resume-{index}",
                    "source": return_site,
                    "target": continuation,
                    "kind": "call_return",
                    "call_site_id": site,
                },
            )
        )
        caller = continuation
    graph, model = _authority(tuple(dict.fromkeys(nodes)), tuple(edges))

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
    assert result.status is TechnicalStatus.CONFIRMED
    assert result.budget_usage.limiting_dimension is None
    assert len(result.recommended.edge_ids) == call_count * 4


def _nested_call_authority() -> tuple[CanonicalGraph, SceneModel]:
    return _authority(
        (
            "root",
            "outer",
            "inner",
            "inner-exit",
            "inner-return-site",
            "outer-after-inner",
            "outer-exit",
            "outer-return-site",
            "target",
        ),
        (
            {
                "id": "outer-enter",
                "source": "root",
                "target": "outer",
                "kind": "call_enter",
                "call_site_id": "outer-site",
            },
            {
                "id": "inner-enter",
                "source": "outer",
                "target": "inner",
                "kind": "call_enter",
                "call_site_id": "inner-site",
            },
            {
                "id": "inner-procedure-return",
                "source": "inner",
                "target": "inner-exit",
                "kind": "call_return",
            },
            {
                "id": "inner-summary",
                "source": "outer",
                "target": "inner-return-site",
                "kind": "call_summary",
                "call_site_id": "inner-site",
            },
            {
                "id": "inner-resume",
                "source": "inner-return-site",
                "target": "outer-after-inner",
                "kind": "call_return",
                "call_site_id": "inner-site",
            },
            {
                "id": "outer-procedure-return",
                "source": "outer-after-inner",
                "target": "outer-exit",
                "kind": "call_return",
            },
            {
                "id": "outer-summary",
                "source": "root",
                "target": "outer-return-site",
                "kind": "call_summary",
                "call_site_id": "outer-site",
            },
            {
                "id": "outer-resume",
                "source": "outer-return-site",
                "target": "target",
                "kind": "call_return",
                "call_site_id": "outer-site",
            },
        ),
    )


def test_nested_calls_pop_only_the_completed_top_frame() -> None:
    graph, model = _nested_call_authority()
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
    assert result.status is TechnicalStatus.CONFIRMED
    assert result.budget_usage.limiting_dimension is None


def test_nested_call_returns_to_the_correct_outer_continuation() -> None:
    graph, model = _nested_call_authority()
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
    assert result.recommended.edge_ids == (
        "outer-enter",
        "inner-enter",
        "inner-procedure-return",
        "inner-summary",
        "inner-resume",
        "outer-procedure-return",
        "outer-summary",
        "outer-resume",
    )


def test_shared_callee_resume_isolated_by_caller_call_site() -> None:
    graph, model = _authority(
        (
            "root",
            "caller-a",
            "caller-b",
            "shared",
            "shared-exit",
            "return-a",
            "return-b",
            "target-a",
            "target-b",
        ),
        (
            {"id": "choose-a", "source": "root", "target": "caller-a"},
            {"id": "choose-b", "source": "root", "target": "caller-b"},
            {
                "id": "enter-a",
                "source": "caller-a",
                "target": "shared",
                "kind": "call_enter",
                "call_site_id": "site-a",
            },
            {
                "id": "enter-b",
                "source": "caller-b",
                "target": "shared",
                "kind": "call_enter",
                "call_site_id": "site-b",
            },
            {
                "id": "shared-return",
                "source": "shared",
                "target": "shared-exit",
                "kind": "call_return",
            },
            {
                "id": "summary-a",
                "source": "caller-a",
                "target": "return-a",
                "kind": "call_summary",
                "call_site_id": "site-a",
            },
            {
                "id": "summary-b",
                "source": "caller-b",
                "target": "return-b",
                "kind": "call_summary",
                "call_site_id": "site-b",
            },
            {
                "id": "resume-a",
                "source": "return-a",
                "target": "target-a",
                "kind": "call_return",
                "call_site_id": "site-a",
            },
            {
                "id": "resume-b",
                "source": "return-b",
                "target": "target-b",
                "kind": "call_return",
                "call_site_id": "site-b",
            },
        ),
        node_kinds={"root": CanonicalNodeKind.CHOICE},
    )
    result = solve_route(
        graph,
        model,
        _solve(
            graph,
            model,
            RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target-a"),
        ),
    ).result

    assert result is not None and result.recommended is not None
    assert result.recommended.edge_ids == (
        "choose-a",
        "enter-a",
        "shared-return",
        "summary-a",
        "resume-a",
    )


def test_genuine_recursion_still_reaches_the_call_depth_bound() -> None:
    depth_gate = _fact(
        "depth-gate",
        kind="requirement",
        expression="depth >= 10",
        variable="depth",
    )
    initial_depth = _fact(
        "initial-depth",
        kind="effect",
        expression="default depth = 0",
        variable="depth",
        operation="assignment",
        value=0,
        initialization=True,
    )
    increment_depth = _fact(
        "increment-depth",
        kind="effect",
        expression="depth += 1",
        variable="depth",
        operation="increment",
        value=1,
    )
    graph, model = _authority(
        (
            "root",
            "recursive",
            "procedure-exit",
            "recursive-return-site",
            "root-return-site",
            "target",
        ),
        (
            {
                "id": "root-enter",
                "source": "root",
                "target": "recursive",
                "kind": "call_enter",
                "call_site_id": "root-site",
            },
            {
                "id": "recursive-enter",
                "source": "recursive",
                "target": "recursive",
                "kind": "call_enter",
                "call_site_id": "recursive-site",
                "effects": (increment_depth.id,),
            },
            {
                "id": "procedure-return",
                "source": "recursive",
                "target": "procedure-exit",
                "kind": "call_return",
            },
            {
                "id": "recursive-summary",
                "source": "recursive",
                "target": "recursive-return-site",
                "kind": "call_summary",
                "call_site_id": "recursive-site",
            },
            {
                "id": "recursive-resume",
                "source": "recursive-return-site",
                "target": "recursive",
                "kind": "call_return",
                "call_site_id": "recursive-site",
            },
            {
                "id": "root-summary",
                "source": "root",
                "target": "root-return-site",
                "kind": "call_summary",
                "call_site_id": "root-site",
            },
            {
                "id": "root-resume",
                "source": "root-return-site",
                "target": "target",
                "kind": "call_return",
                "call_site_id": "root-site",
                "gates": (depth_gate.id,),
            },
        ),
        facts=(depth_gate, initial_depth, increment_depth),
        node_facts={"root": (initial_depth.id,)},
    )
    depth = StateVariableIdentity("store", "depth", None)
    result = solve_route(
        graph,
        model,
        _solve(
            graph,
            model,
            RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
            initial=(
                InitialStateValue(
                    depth,
                    InitialValueKind.KNOWN,
                    0,
                    ("evidence-initial-depth",),
                ),
            ),
            limits=DeterministicLimitProfile(call_depth=4),
        ),
    ).result

    assert result is not None
    assert result.status is TechnicalStatus.INCOMPLETE
    assert result.budget_usage.limiting_dimension == "call_depth"
    assert result.complete is False


@pytest.mark.parametrize("resolved", (True, False))
def test_malformed_or_unresolved_return_remains_conservative(resolved: bool) -> None:
    graph, model = _authority(
        ("root", "target"),
        (
            {
                "id": "orphan-return",
                "source": "root",
                "target": "target",
                "kind": "call_return",
                "call_site_id": "missing-site",
                "resolved": resolved,
            },
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

    assert result is not None
    assert result.recommended is None
    assert result.status is TechnicalStatus.DYNAMIC_POSSIBILITY
