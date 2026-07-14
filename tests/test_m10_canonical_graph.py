from __future__ import annotations

import copy
from pathlib import Path

import pytest

from renpy_story_mapper.canonical_graph import build_canonical_graph
from renpy_story_mapper.canonical_graph_contract import (
    CANONICAL_GRAPH_SCHEMA_VERSION,
    CanonicalGraph,
    CanonicalNode,
    ReachabilityStatus,
    assign_reachability,
    source_generation,
)
from renpy_story_mapper.control_flow import analyze_control_flow
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.route_map import project_route_map
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.state import extract_state

FIXTURE = Path(__file__).parent / "fixtures" / "m10" / "canonical_constructs.rpy"
CALL_RETURN_FIXTURE = Path(__file__).parent / "fixtures" / "call_return.rpy"


def _canonical_for_source(source: str) -> CanonicalGraph:
    module = parse_script("regression.rpy", source.splitlines(keepends=True))
    graph = build_graph([module])
    semantic = build_semantic_story(graph)
    state = extract_state([module])
    control = analyze_control_flow(
        graph, semantic, state.requirements, state.effects
    ).to_dict()
    route = project_route_map(control, semantic, state.requirements, state.effects)
    return build_canonical_graph(
        graph,
        semantic,
        control,
        route,
        state,
        source_generation=source_generation(((module.path, "a" * 64),)),
    )


def _node_by_source(
    canonical: CanonicalGraph, source_text: str, *, label: str | None = None
) -> CanonicalNode:
    return next(
        item
        for item in canonical.nodes
        if item.attributes.get("source_text") == source_text
        and (label is None or item.label == label)
    )


@pytest.mark.parametrize(
    ("inputs", "expected"),
    [
        ({"static_reachable": True}, ReachabilityStatus.PROVEN_REACHABLE),
        (
            {"static_reachable": True, "proven_requirement": True},
            ReachabilityStatus.CONDITIONALLY_REACHABLE,
        ),
        (
            {"static_reachable": True, "inferred_requirement": True},
            ReachabilityStatus.REACHABLE_UNDER_INFERRED_REQUIREMENTS,
        ),
        (
            {"static_reachable": True, "unresolved_requirement": True},
            ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR,
        ),
        (
            {"static_reachable": False, "unresolved_item": True},
            ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR,
        ),
        (
            {"static_reachable": False, "unresolved_transfer_could_reach": True},
            ReachabilityStatus.POSSIBLY_DEAD,
        ),
        (
            {"static_reachable": False, "closed_world": False},
            ReachabilityStatus.UNREACHABLE_IN_RESOLVED_STATIC_GRAPH,
        ),
        (
            {"static_reachable": False, "closed_world": True},
            ReachabilityStatus.PROVEN_UNREACHABLE,
        ),
    ],
)
def test_reachability_decision_table(
    inputs: dict[str, bool], expected: ReachabilityStatus
) -> None:
    assert assign_reachability(**inputs) is expected  # type: ignore[arg-type]


def test_canonical_graph_composes_existing_authority_and_is_permutation_stable() -> None:
    module = parse_script(
        "m10/canonical_constructs.rpy",
        FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True),
    )
    graph = build_graph([module])
    semantic = build_semantic_story(graph)
    state = extract_state([module])
    control = analyze_control_flow(
        graph, semantic, state.requirements, state.effects
    ).to_dict()
    route = project_route_map(control, semantic, state.requirements, state.effects)
    generation = source_generation(((module.path, "a" * 64),))
    first = build_canonical_graph(
        graph, semantic, control, route, state, source_generation=generation
    )

    assert first.to_dict()["schema_version"] == CANONICAL_GRAPH_SCHEMA_VERSION
    assert first.regions
    assert {item.kind for item in first.facts} == {"requirement", "effect"}
    assert any(item.kind == "loop_choice" for item in first.regions)
    assert any(item.kind == "unresolved" for item in first.nodes)
    assert all(item.evidence_ids or item.proof_ids for item in (*first.nodes, *first.edges))
    assert all(item.origins for item in (*first.nodes, *first.edges, *first.regions))
    assert {
        "branch_arm_membership",
        "call_site_return_continuation",
        "immediate_post_dominator_merge",
        "resolved_static_reachability",
        "scc_loop_membership",
        "terminal_classification",
    } <= {item.kind for item in first.proofs}
    assert all(item.origins and item.input_ids and item.explanation for item in first.proofs)

    permuted_graph = copy.deepcopy(graph)
    permuted_semantic = copy.deepcopy(semantic)
    permuted_control = copy.deepcopy(control)
    for value in (permuted_graph, permuted_semantic, permuted_control):
        for key, rows in tuple(value.items()):
            if isinstance(rows, list):
                value[key] = list(reversed(rows))
    second = build_canonical_graph(
        permuted_graph,
        permuted_semantic,
        permuted_control,
        route,
        state,
        source_generation=generation,
    )
    assert second.normalized_bytes() == first.normalized_bytes()
    assert second.authority_hash == first.authority_hash


def test_resolved_m06_call_nodes_and_edges_are_reachable_with_proof() -> None:
    module = parse_script(
        "call_return.rpy",
        CALL_RETURN_FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True),
    )
    graph = build_graph([module])
    semantic = build_semantic_story(graph)
    state = extract_state([module])
    control = analyze_control_flow(
        graph, semantic, state.requirements, state.effects
    ).to_dict()
    route = project_route_map(control, semantic, state.requirements, state.effects)
    canonical = build_canonical_graph(
        graph,
        semantic,
        control,
        route,
        state,
        source_generation=source_generation(((module.path, "a" * 64),)),
    )

    synthetic = {
        str(item.attributes.get("source_kind")): item
        for item in canonical.nodes
        if item.attributes.get("synthetic")
    }
    assert (
        synthetic["procedure_return_boundary"].reachability
        is ReachabilityStatus.PROVEN_REACHABLE
    )
    assert synthetic["call_return_site"].reachability is ReachabilityStatus.PROVEN_REACHABLE

    proof_by_id = {item.id: item for item in canonical.proofs}
    for node in synthetic.values():
        assert any(
            proof_by_id[proof_id].kind == "resolved_static_reachability"
            for proof_id in node.proof_ids
        )

    relevant_edges = [
        item
        for item in canonical.edges
        if item.kind in {"call_enter", "call_summary", "call_return"}
    ]
    assert relevant_edges
    assert all(
        item.reachability is ReachabilityStatus.PROVEN_REACHABLE
        for item in relevant_edges
    )
    assert any(
        proof_by_id[proof_id].kind == "call_site_return_continuation"
        for item in relevant_edges
        for proof_id in item.proof_ids
    )


def test_persistent_if_guards_propagate_with_ordered_predicate_provenance() -> None:
    canonical = _canonical_for_source(
        """label start:
    if score >= 5:
        jump secret
    jump normal

label secret:
    \"Hidden scene\"
    return

label normal:
    \"Normal scene\"
    return
"""
    )

    for source_text in ('jump secret', 'label secret:', '"Hidden scene"'):
        node = _node_by_source(canonical, source_text)
        assert node.reachability is ReachabilityStatus.CONDITIONALLY_REACHABLE
        assert node.attributes["guard_dependencies"]

    region = next(item for item in canonical.regions if item.merge_node_id is None)
    arms = sorted(region.attributes["arms"], key=lambda item: item["ordinal"])
    positive = arms[0]["predicate"]
    assert positive["kind"] == "if_branch"
    assert positive["expression"] == "score >= 5"
    assert positive["polarity"] == "positive"
    assert positive["branch_order"] == 0
    assert positive["source"] == "m01_graph_edge_metadata"
    assert positive["origin"]["collection"] == "m06_control_flow"
    assert positive["origin"]["subpath"] == "evidence.metadata.condition"
    assert positive["requirement_fact_ids"]
    assert positive["status"] == "proven"
    assert arms[1]["predicate"]["kind"] == "if_fallthrough"
    assert arms[1]["predicate"]["expressions"] == ["score >= 5"]
    assert arms[1]["predicate"]["polarity"] == "none_true"
    assert arms[1]["predicate"]["branch_order"] == 1
    assert "expression" not in arms[1]["predicate"]


def test_conditional_menu_choice_guards_its_body_node_and_edge() -> None:
    canonical = _canonical_for_source(
        """label start:
    menu:
        \"Help\" if ready:
            $ trust += 1
        \"Leave\":
            return
"""
    )

    choice = _node_by_source(canonical, '"Help" if ready:')
    body = _node_by_source(canonical, '$ trust += 1')
    body_edge = next(
        edge
        for edge in canonical.edges
        if edge.source_id == choice.id and edge.target_id == body.id
    )
    assert choice.reachability is ReachabilityStatus.CONDITIONALLY_REACHABLE
    assert body.reachability is ReachabilityStatus.CONDITIONALLY_REACHABLE
    assert body_edge.reachability is ReachabilityStatus.CONDITIONALLY_REACHABLE
    assert body.attributes["guard_dependencies"][0]["expression"] == "ready"
    assert body_edge.attributes["guard_dependencies"][0]["expression"] == "ready"


def test_nested_guards_accumulate_and_stop_at_each_proven_merge() -> None:
    canonical = _canonical_for_source(
        """label start:
    if outer_ready:
        if inner_ready:
            \"Nested\"
        \"Outer only\"
    \"After both\"
    return
"""
    )

    nested = _node_by_source(canonical, '"Nested"')
    outer_only = _node_by_source(canonical, '"Outer only"')
    after_both = _node_by_source(canonical, '"After both"')
    assert nested.reachability is ReachabilityStatus.CONDITIONALLY_REACHABLE
    assert [
        item["expression"] for item in nested.attributes["guard_dependencies"]
    ] == ["outer_ready", "inner_ready"]
    assert [item["depth"] for item in nested.attributes["guard_dependencies"]] == [0, 1]
    assert [
        item["expression"] for item in outer_only.attributes["guard_dependencies"]
    ] == ["outer_ready"]
    assert after_both.reachability is ReachabilityStatus.PROVEN_REACHABLE
    assert after_both.attributes["guard_dependencies"] == []


def test_unconditional_menu_no_choice_cannot_reach_a_hidden_scene() -> None:
    canonical = _canonical_for_source(
        """label start:
    menu:
        "Stay":
            return
    jump hidden

label hidden:
    "Hidden scene"
    return
"""
    )

    no_choice = next(
        item
        for item in canonical.edges
        if "menu_no_choice" in item.attributes["semantic_roles"]
    )
    assert no_choice.attributes["predicate"]["feasibility"] == "impossible"
    assert no_choice.attributes["predicate"]["status"] == "impossible"
    assert no_choice.reachability is ReachabilityStatus.PROVEN_UNREACHABLE
    for source_text in ("jump hidden", "label hidden:", '"Hidden scene"'):
        node = _node_by_source(canonical, source_text)
        assert node.reachability is ReachabilityStatus.PROVEN_UNREACHABLE
        assert node.attributes["resolved_static_reachable"] is False
        assert node.attributes["guard_dependencies"] == []


def test_all_conditional_menu_no_choice_links_negative_sibling_requirements() -> None:
    canonical = _canonical_for_source(
        """label start:
    menu:
        "Alpha" if alpha:
            return
        "Beta" if beta:
            return
    jump fallback

label fallback:
    "Fallback scene"
    return
"""
    )

    no_choice = next(
        item
        for item in canonical.edges
        if "menu_no_choice" in item.attributes["semantic_roles"]
    )
    predicate = no_choice.attributes["predicate"]
    assert predicate["feasibility"] == "conditional"
    assert predicate["status"] == "proven"
    assert predicate["operator"] == "and"
    assert [
        (item["expression"], item["polarity"], item["branch_order"])
        for item in predicate["conditions"]
    ] == [("alpha", "negative", 0), ("beta", "negative", 1)]
    assert all(item["requirement_fact_ids"] for item in predicate["conditions"])
    assert set(predicate["requirement_fact_ids"]) == {
        fact_id
        for item in predicate["conditions"]
        for fact_id in item["requirement_fact_ids"]
    }
    assert not any(
        str(item["expression"]).startswith("not ") for item in predicate["conditions"]
    )
    assert no_choice.reachability is ReachabilityStatus.CONDITIONALLY_REACHABLE
    fallback = _node_by_source(canonical, '"Fallback scene"')
    assert fallback.reachability is ReachabilityStatus.CONDITIONALLY_REACHABLE
    dependency = fallback.attributes["guard_dependencies"][0]
    assert dependency["conditions"] == predicate["conditions"]


@pytest.mark.parametrize(
    "menu_source",
    [
        """menu:
        set seen
        "Stay":
            return""",
        """menu (screen="custom_choice"):
        "Stay":
            return""",
    ],
)
def test_menu_no_choice_with_unresolved_availability_stays_unresolved(
    menu_source: str,
) -> None:
    canonical = _canonical_for_source(
        f"""label start:
    {menu_source}
    "After menu"
    return
"""
    )

    no_choice = next(
        item
        for item in canonical.edges
        if "menu_no_choice" in item.attributes["semantic_roles"]
    )
    assert no_choice.attributes["predicate"]["feasibility"] == "unresolved"
    assert no_choice.attributes["predicate"]["status"] == "unresolved"
    assert no_choice.reachability is ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR
    no_choice_arm = next(
        arm
        for region in canonical.regions
        for arm in region.attributes["arms"]
        if arm["edge_id"] == no_choice.id
    )
    assert no_choice_arm["unresolved"] is True


def test_ordered_if_predicates_preserve_all_prior_sibling_conditions() -> None:
    canonical = _canonical_for_source(
        """label start:
    if alpha:
        "Alpha"
    elif beta:
        "Beta"
    elif gamma:
        "Gamma"
    else:
        "Else"
    return
"""
    )

    expected = {
        '"Alpha"': [("alpha", "positive", 0)],
        '"Beta"': [("alpha", "negative", 0), ("beta", "positive", 1)],
        '"Gamma"': [
            ("alpha", "negative", 0),
            ("beta", "negative", 1),
            ("gamma", "positive", 2),
        ],
        '"Else"': [
            ("alpha", "negative", 0),
            ("beta", "negative", 1),
            ("gamma", "negative", 2),
        ],
    }
    region = next(
        item
        for item in canonical.regions
        if len(item.attributes["arms"]) == len(expected)
    )
    arms = sorted(region.attributes["arms"], key=lambda item: item["ordinal"])
    canonical_by_id = {item.id: item for item in canonical.nodes}
    edge_by_id = {item.id: item for item in canonical.edges}
    for arm, (source_text, expected_conditions) in zip(arms, expected.items(), strict=True):
        body = _node_by_source(canonical, source_text)
        dependency = body.attributes["guard_dependencies"][0]
        conditions = dependency["conditions"]
        assert [
            (item["expression"], item["polarity"], item["branch_order"])
            for item in conditions
        ] == expected_conditions
        assert all(item["requirement_fact_ids"] for item in conditions)
        expected_fact_ids = {
            fact_id for item in conditions for fact_id in item["requirement_fact_ids"]
        }
        assert set(dependency["requirement_fact_ids"]) == expected_fact_ids

        entry = canonical_by_id[arm["entry_node_id"]]
        controlling_edge = edge_by_id[arm["edge_id"]]
        assert controlling_edge.target_id == entry.id
        assert controlling_edge.attributes["predicate"]["conditions"] == conditions
        assert controlling_edge.attributes["guard_dependencies"][0]["conditions"] == conditions
        assert set(controlling_edge.attributes["gate_ids"]) == expected_fact_ids
        assert arm["predicate"]["conditions"] == conditions
        assert arm["predicate"]["operator"] == "and"


def test_guarded_only_call_keeps_the_callee_conditional() -> None:
    canonical = _canonical_for_source(
        """label start:
    if ready:
        call helper
    return

label helper:
    "Helper scene"
    return
"""
    )

    helper_nodes = [
        _node_by_source(canonical, "label helper:"),
        _node_by_source(canonical, '"Helper scene"'),
        _node_by_source(canonical, "return", label="helper"),
        next(
            item
            for item in canonical.nodes
            if item.label == "helper"
            and item.attributes.get("source_kind") == "procedure_return_boundary"
        ),
    ]
    for node in helper_nodes:
        assert node.reachability is ReachabilityStatus.CONDITIONALLY_REACHABLE
        assert node.attributes["guard_dependencies"][0]["expression"] == "ready"
        assert node.attributes["guard_dependencies"][0]["polarity"] == "positive"


@pytest.mark.parametrize("unguarded_transfer", ["call shared", "jump shared"])
def test_unguarded_call_or_jump_makes_a_shared_callee_proven(
    unguarded_transfer: str,
) -> None:
    canonical = _canonical_for_source(
        f"""label start:
    if ready:
        call shared
    {unguarded_transfer}
    return

label shared:
    "Shared scene"
    return
"""
    )

    for source_text in ("label shared:", '"Shared scene"'):
        node = _node_by_source(canonical, source_text)
        assert node.reachability is ReachabilityStatus.PROVEN_REACHABLE
        assert node.attributes["guard_dependencies"] == []
        assert [] in node.attributes["guard_alternatives"]


def test_multiple_guarded_callers_retain_bounded_entry_alternatives() -> None:
    canonical = _canonical_for_source(
        """label start:
    menu:
        "Alpha" if alpha:
            call shared
            return
        "Beta" if beta:
            call shared
            return
        "Leave":
            return

label shared:
    "Shared scene"
    return
"""
    )

    shared = _node_by_source(canonical, "label shared:")
    assert shared.reachability is ReachabilityStatus.CONDITIONALLY_REACHABLE
    alternatives = shared.attributes["guard_alternatives"]
    assert 1 < len(alternatives) <= 8
    assert {
        tuple(item["expression"] for item in alternative)
        for alternative in alternatives
    } == {("alpha",), ("beta",)}
    assert all(
        item["requirement_fact_ids"]
        for alternative in alternatives
        for item in alternative
    )

    incoming = [
        item
        for item in canonical.edges
        if item.target_id == shared.id and item.kind == "call_enter"
    ]
    assert len(incoming) == 2
    assert {
        item.attributes["guard_dependencies"][0]["expression"] for item in incoming
    } == {"alpha", "beta"}


def test_nested_guarded_calls_propagate_the_entry_context() -> None:
    canonical = _canonical_for_source(
        """label start:
    if outer:
        call first
    return

label first:
    "First scene"
    call second
    return

label second:
    "Second scene"
    return
"""
    )

    for source_text in (
        "label first:",
        '"First scene"',
        "call second",
        "label second:",
        '"Second scene"',
    ):
        node = _node_by_source(canonical, source_text)
        assert node.reachability is ReachabilityStatus.CONDITIONALLY_REACHABLE
        assert node.attributes["guard_dependencies"][0]["expression"] == "outer"
    inner_call = _node_by_source(canonical, "call second")
    inner_enter = next(
        item
        for item in canonical.edges
        if item.source_id == inner_call.id and item.kind == "call_enter"
    )
    assert inner_enter.reachability is ReachabilityStatus.CONDITIONALLY_REACHABLE
    assert inner_enter.attributes["guard_dependencies"][0]["expression"] == "outer"


def test_return_continuations_remain_isolated_by_call_site() -> None:
    canonical = _canonical_for_source(
        """label start:
    menu:
        "Alpha" if alpha:
            call shared
            "After alpha"
            return
        "Beta" if beta:
            call shared
            "After beta"
            return
        "Leave":
            return

label shared:
    "Shared scene"
    return
"""
    )

    expected_by_call_site = {
        item.graph_node_id: item.attributes["guard_dependencies"][0]["expression"]
        for item in canonical.nodes
        if item.attributes.get("source_kind") == "call"
    }
    assert set(expected_by_call_site.values()) == {"alpha", "beta"}
    for edge in canonical.edges:
        call_site_id = edge.attributes.get("call_site_id")
        if call_site_id not in expected_by_call_site:
            continue
        assert edge.kind in {"call_enter", "call_summary", "call_return"}
        assert edge.attributes["guard_dependencies"][0]["expression"] == (
            expected_by_call_site[call_site_id]
        )

    after_alpha = _node_by_source(canonical, '"After alpha"')
    after_beta = _node_by_source(canonical, '"After beta"')
    assert [
        item["expression"] for item in after_alpha.attributes["guard_dependencies"]
    ] == ["alpha"]
    assert [
        item["expression"] for item in after_beta.attributes["guard_dependencies"]
    ] == ["beta"]

    shared_exit = next(
        item
        for item in canonical.nodes
        if item.label == "shared"
        and item.attributes.get("source_kind") == "procedure_return_boundary"
    )
    assert {
        tuple(item["expression"] for item in alternative)
        for alternative in shared_exit.attributes["guard_alternatives"]
    } == {("alpha",), ("beta",)}
    assert not any(
        item.source_id == shared_exit.id
        and item.target_id in {after_alpha.id, after_beta.id}
        for item in canonical.edges
    )


def test_reachability_witness_inputs_preserve_predecessor_field_order() -> None:
    canonical = _canonical_for_source(
        """label start:
    \"One\"
    \"Two\"
    return
"""
    )
    proof_by_id = {item.id: item for item in canonical.proofs}
    node = next(
        item
        for item in canonical.nodes
        if item.attributes.get("reachability_witness", {}).get("kind") == "predecessor"
    )
    witness = node.attributes["reachability_witness"]
    proof = next(
        proof_by_id[proof_id]
        for proof_id in node.proof_ids
        if proof_by_id[proof_id].kind == "resolved_static_reachability"
    )
    assert proof.input_ids == (
        witness["root_node_id"],
        witness["parent_node_id"],
        witness["edge_id"],
        witness["node_id"],
    )
    assert proof.to_dict()["input_ids"] == list(proof.input_ids)


def test_edge_reachability_comes_from_its_source_not_an_alternate_target_path() -> None:
    canonical = _canonical_for_source(
        """label start:
    jump live

label dead:
    jump live

label live:
    \"Live\"
    return
"""
    )

    dead_jump = _node_by_source(canonical, "jump live", label="dead")
    live = _node_by_source(canonical, "label live:")
    dead_edge = next(
        edge
        for edge in canonical.edges
        if edge.source_id == dead_jump.id and edge.target_id == live.id
    )
    assert dead_jump.reachability is ReachabilityStatus.PROVEN_UNREACHABLE
    assert live.reachability is ReachabilityStatus.PROVEN_REACHABLE
    assert dead_edge.reachability is ReachabilityStatus.PROVEN_UNREACHABLE
    proof_by_id = {item.id: item for item in canonical.proofs}
    assert any(
        proof_by_id[proof_id].kind == "edge_reachability"
        for proof_id in dead_edge.proof_ids
    )


def test_conditional_edge_stays_conditional_when_target_has_an_unguarded_path() -> None:
    canonical = _canonical_for_source(
        """label start:
    menu:
        "Guarded" if ready:
            jump shared
        "Open":
            jump shared

label shared:
    \"Shared\"
    return
"""
    )

    guarded_jump = next(
        item
        for item in canonical.nodes
        if item.label == "start"
        and item.attributes.get("source_text") == "jump shared"
        and item.reachability is ReachabilityStatus.CONDITIONALLY_REACHABLE
    )
    shared = _node_by_source(canonical, "label shared:")
    guarded_edge = next(
        edge
        for edge in canonical.edges
        if edge.source_id == guarded_jump.id and edge.target_id == shared.id
    )
    assert shared.reachability is ReachabilityStatus.PROVEN_REACHABLE
    assert guarded_edge.reachability is ReachabilityStatus.CONDITIONALLY_REACHABLE


def test_unresolved_edges_remain_unresolved() -> None:
    canonical = _canonical_for_source(
        """label start:
    jump expression destination
"""
    )

    unresolved_edges = [item for item in canonical.edges if item.kind == "unresolved"]
    assert unresolved_edges
    assert all(
        item.reachability is ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR
        for item in unresolved_edges
    )


def test_project_persists_canonical_graph_with_matching_fact_origins(tmp_path: Path) -> None:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    project_path = tmp_path / "story.rsmproj"

    with create_ingested_project(project_path, source) as project:
        payload = project.payload("m10_canonical_graph", "authoritative")
        assert isinstance(payload, dict)
        assert payload["schema_version"] == CANONICAL_GRAPH_SCHEMA_VERSION
        source_rows = project._require_open().execute(
            "SELECT path,content_hash FROM sources ORDER BY path"
        )
        expected_generation = source_generation(
            tuple((str(row["path"]), str(row["content_hash"])) for row in source_rows)
        )
        assert payload["source_generation"] == expected_generation
        origins = {
            str(origin["record_id"])
            for fact in payload["facts"]
            for origin in fact["origins"]
        }
        persisted = {
            str(item["id"])
            for collection in ("gates", "effects", "unresolved")
            for key in project.payload_keys(collection)
            for item in (project.payload(collection, key) or [])
            if isinstance(item, dict) and "id" in item
        }
        assert origins <= persisted
        normalized = payload

    with Project.open(project_path) as project:
        assert project.payload("m10_canonical_graph", "authoritative") == normalized
