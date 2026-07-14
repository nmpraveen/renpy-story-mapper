from __future__ import annotations

import gc
from dataclasses import dataclass

from renpy_story_mapper.canonical_graph import build_canonical_graph
from renpy_story_mapper.canonical_graph_contract import source_generation
from renpy_story_mapper.control_flow import analyze_control_flow
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.route_map import project_route_map
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.state import extract_state


@dataclass(frozen=True)
class _ScaleMetrics:
    statements: int
    node_count: int
    reachability_inputs: int
    canonical_bytes: int


def _scale_metrics(statements: int) -> _ScaleMetrics:
    source = "label start:\n" + "".join(
        f'    "Linear statement {index}."\n' for index in range(statements)
    )
    module = parse_script("linear-scale.rpy", source.splitlines(keepends=True))
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
    metrics = _ScaleMetrics(
        statements,
        len(canonical.nodes),
        sum(
            len(proof.input_ids)
            for proof in canonical.proofs
            if proof.kind == "resolved_static_reachability"
        ),
        len(canonical.normalized_bytes()),
    )
    del canonical, control, route, state, semantic, graph, module
    gc.collect()
    return metrics


def test_linear_reachability_provenance_and_payload_growth_are_bounded() -> None:
    at_500 = _scale_metrics(500)
    at_1000 = _scale_metrics(1_000)
    at_2000 = _scale_metrics(2_000)

    assert at_2000.reachability_inputs <= 4 * at_2000.node_count, at_2000
    assert at_2000.canonical_bytes < 12_000_000, at_2000
    assert at_1000.canonical_bytes < at_500.canonical_bytes * 2.6, (
        at_500,
        at_1000,
    )
