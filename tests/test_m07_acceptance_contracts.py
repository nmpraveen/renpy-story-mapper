from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import re
from collections import Counter
from dataclasses import fields
from pathlib import Path
from typing import Any

from renpy_story_mapper.control_flow import FlowEdgeRole, analyze_control_flow
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.state import extract_state
from renpy_story_mapper.m07_model import M07ModelService
from renpy_story_mapper.organization.parallel import (
    BudgetPolicy,
    CheckpointSink,
    ParallelOrganizationScheduler,
    SchedulerConfig,
    normalized_cache_identity,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "m07"
STATIC = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
HARNESS = ROOT / "scripts" / "m07_browser_acceptance.py"


def _mapping(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return value


def _sequence(value: object) -> list[Any]:
    assert isinstance(value, list)
    return value


def _json(name: str) -> dict[str, Any]:
    return _mapping(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def _canonical_text_hash(path: Path) -> str:
    content = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _analysis() -> tuple[dict[str, Any], Any, Any, dict[str, Any]]:
    path = FIXTURES / "route_topology.rpy"
    module = parse_script(
        "m07/route_topology.rpy", path.read_text(encoding="utf-8").splitlines(keepends=True)
    )
    graph = build_graph([module])
    semantic = build_semantic_story(graph)
    state = extract_state([module])
    control = analyze_control_flow(graph, semantic, state.requirements, state.effects)
    return graph, state, control, semantic


def test_fixture_manifest_hashes_and_physical_evidence_are_exact() -> None:
    manifest = _json("manifest.json")
    files = _mapping(manifest["files"])
    for name, expected_value in files.items():
        expected = _mapping(expected_value)
        path = FIXTURES / name
        assert path.is_file()
        assert _canonical_text_hash(path) == expected["sha256"]
        if "physical_line_count" in expected:
            assert len(path.read_text(encoding="utf-8").splitlines()) == expected[
                "physical_line_count"
            ]

    source_lines = (FIXTURES / "route_topology.rpy").read_text(encoding="utf-8").splitlines()
    evidence = _sequence(manifest["evidence"])
    assert len({item["id"] for item in evidence}) == len(evidence)
    for record_value in evidence:
        record = _mapping(record_value)
        assert record["path"] == "m07/route_topology.rpy"
        assert source_lines[int(record["line"]) - 1].strip() == record["text"]


def test_synthetic_fixture_baseline_pipeline_is_deterministic_and_nonexecuting() -> None:
    graph, state, control, semantic = _analysis()
    observed = _mapping(_json("manifest.json")["observed_baseline_pipeline"])
    counts = _mapping(graph["counts"])
    assert counts["nodes"] == observed["graph_nodes"]
    assert counts["edges"] == observed["graph_edges"]
    assert counts["unresolved"] == observed["graph_unresolved"]
    assert counts["labels_in_scope"] == observed["labels_in_scope"]
    assert len(_sequence(semantic["scenes"])) == observed["semantic_scenes"]
    assert len(_sequence(semantic["beats"])) == observed["semantic_beats"]
    assert len(_sequence(semantic["transitions"])) == observed["semantic_transitions"]
    assert len(_sequence(semantic["unresolved"])) == observed["semantic_unresolved"]
    assert len(state.requirements) == observed["requirements"]
    assert len(state.effects) == observed["effects"]
    assert len(state.variables) == observed["state_variables"]
    assert graph["semantics"]["expressions_evaluated"] is False
    assert graph["semantics"]["creator_code_executed"] is False

    first = control.canonical_json()
    permuted = dict(graph)
    permuted["nodes"] = list(reversed(_sequence(graph["nodes"])))
    permuted["edges"] = list(reversed(_sequence(graph["edges"])))
    second = analyze_control_flow(
        permuted,
        build_semantic_story(permuted),
        state.requirements,
        state.effects,
    ).canonical_json()
    assert second == first


def test_fixture_exercises_routes_nested_detours_calls_loop_and_unresolved() -> None:
    _, state, control, _ = _analysis()
    expected = _mapping(_json("manifest.json")["observed_baseline_pipeline"])
    classifications = Counter(region.classification.value for region in control.regions)
    assert classifications == Counter(_mapping(expected["control_regions"]))
    assert len(control.loops) == expected["loops"]
    assert any(edge.role is FlowEdgeRole.LOOP_BODY for edge in control.edges)
    assert all(loop.node_ids and loop.exit_edge_ids for loop in control.loops)
    assert sum(edge.role is FlowEdgeRole.CALL_SUMMARY for edge in control.edges) == 2
    assert len([node for node in control.nodes if node.kind == "call_return_site"]) == 2
    assert any(
        diagnostic.kind == "dynamic_target" or "unresolved" in diagnostic.kind
        for diagnostic in control.diagnostics
    ) or any(reason == "unresolved" for _, reason in control.terminals)

    expressions = {item.original_expression for item in state.requirements}
    assert expressions == {
        "wits >= 2",
        "money >= 10",
        "red_points >= 3",
        "blue_points >= 3",
        "courage >= 5",
    }
    effects = {item.original_expression for item in state.effects}
    assert {
        "love += 1",
        "money -= 10",
        'route = "red"',
        'route = "blue"',
        "dating = True",
        'job = "Harbor"',
    } <= effects


def test_provider_timelines_cover_every_locked_adversarial_behavior() -> None:
    fixture = _json("provider_timelines.json")
    assert fixture["model"] == "gpt-5.6-luna"
    assert fixture["reasoning"] == "high"
    assert fixture["fast_mode"] is False
    assert fixture["limits"] == {
        "initial_concurrency": 8,
        "maximum_concurrency": 12,
        "maximum_repairs": 2,
    }
    scenarios = _mapping(fixture["scenarios"])
    assert set(scenarios) == {
        "shuffled_completion",
        "cancellation_resume",
        "cache_replay",
        "rate_limit_throttle",
        "latency_adaptation",
        "bounded_repairs",
        "hard_token_budget",
        "soft_partial_coverage",
        "per_attempt_usage_failure",
        "normalized_identity",
    }
    for scenario_value in scenarios.values():
        scenario = _mapping(scenario_value)
        events = [_mapping(item) for item in _sequence(scenario["events"])]
        assert [event["tick"] for event in events] == sorted(event["tick"] for event in events)
        assert set(scenario["scopes"])
        assert all(
            "scope" not in event or event["scope"] in set(scenario["scopes"])
            for event in events
        )

    shuffled = _mapping(scenarios["shuffled_completion"])
    completion = [
        event["scope"]
        for event in _sequence(shuffled["events"])
        if event["event"] == "validated"
    ]
    assert completion != shuffled["expected_assembly"]
    assert shuffled["expected_assembly"] == shuffled["scopes"]

    cancellation = _mapping(scenarios["cancellation_resume"])
    before_resume = []
    for event in _sequence(cancellation["events"]):
        if event["event"] == "resume":
            break
        if event["event"] == "validated":
            before_resume.append(event["scope"])
    assert before_resume == cancellation["validated_before_resume"]
    assert cancellation["expected_resume_calls"] == 2

    replay = _mapping(scenarios["cache_replay"])
    assert replay["expected_calls"] == 0
    assert all(event["event"] == "cached" for event in _sequence(replay["events"]))
    rate_limit = _mapping(scenarios["rate_limit_throttle"])
    assert rate_limit["expected_peak_after_signal"] == 4
    assert rate_limit["expected_attempts"] == 2
    latency = _mapping(scenarios["latency_adaptation"])
    assert latency["expected_next_timeout_ticks"] == 16

    repair_events = _sequence(_mapping(scenarios["bounded_repairs"])["events"])
    active_repairs = 0
    peak_repairs = 0
    for event in repair_events:
        if event["event"] == "repair_started":
            active_repairs += 1
            peak_repairs = max(peak_repairs, active_repairs)
        elif event["event"] in {"validated", "fallback", "failed"}:
            active_repairs -= 1
    assert peak_repairs == 2

    budget = _mapping(scenarios["hard_token_budget"])
    assert budget["expected_consumed_tokens"] == 90
    assert budget["expected_calls"] == 1
    partial = _mapping(scenarios["soft_partial_coverage"])
    assert partial["expected"] == {
        "ai_scopes": 2,
        "technical_scopes": 1,
        "pending_scopes": 1,
        "reviewable": True,
    }
    usage = _mapping(scenarios["per_attempt_usage_failure"])
    assert usage["expected"] == {
        "calls": 2,
        "input_tokens": 82,
        "output_tokens": 8,
        "failures": 1,
    }
    identity = _mapping(scenarios["normalized_identity"])
    identities = {
        event["cache_identity"]
        for event in _sequence(identity["events"])
        if "cache_identity" in event
    }
    assert identities == {"sha256:identical-a"}
    assert identity["expected_calls"] == 1


def test_browser_fixture_and_harness_define_exactly_two_local_levels() -> None:
    contract = _json("browser_contract.json")
    source = HARNESS.read_text(encoding="utf-8")
    assert contract["levels"] == ["route_map", "detail_evidence"]
    assert contract["only_level_transition_label"] == "Back to Route Map"
    assert contract["initial_node_limit"] == 30
    assert contract["render_item_limit"] == 240
    assert contract["zoom_percentages"] == [100, 200]
    assert contract["network"] == {"allowed_origins": ["127.0.0.1"], "remote_requests": 0}
    assert "--force-device-scale-factor=2" in source
    assert "720,450" in source and "1440,900" in source
    assert "provider_constructions" in source
    assert '"remote_requests": 0' in source
    assert "Back to Route Map" in source
    assert 'list.addEventListener("click"' in source
    assert 'event.key==="Enter"' in source
    assert "Open Detail" not in source
    assert "Level 3" not in source and "third level" not in source.casefold()
    spec = importlib.util.spec_from_file_location("m07_browser_acceptance", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assets = "\n".join(text for _, text in module.ASSETS.values())
    assert not re.search(r"(?:https?:)?//(?!127\.0\.0\.1|localhost)", assets, re.IGNORECASE)
    assert module.STATES == (
        "route-map",
        "detail-evidence",
        "coverage-progress",
        "review-partial",
    )


def test_public_scope_checkpoint_contract_is_durable_and_queryable() -> None:
    required = {"checkpoints", "transition", "record_attempt", "coverage", "assemble"}
    assert required <= set(dir(M07ModelService))
    transition = inspect.signature(M07ModelService.transition).parameters
    assert {"scope_id", "status", "result", "error_code"} <= set(transition)
    assert "attempt" in inspect.signature(M07ModelService.record_attempt).parameters


def test_public_parallel_workflow_exposes_locked_policy_and_resume() -> None:
    config_fields = {field.name for field in fields(SchedulerConfig)}
    assert {"initial_workers", "maximum_workers", "maximum_repairs", "budget"} <= config_fields
    budget_fields = {field.name for field in fields(BudgetPolicy)}
    assert {"soft_tokens", "hard_tokens", "hard_calls"} <= budget_fields
    assert hasattr(ParallelOrganizationScheduler, "run")
    assert hasattr(CheckpointSink, "checkpoint")
    assert callable(normalized_cache_identity)


def test_production_browser_contract_removes_all_third_level_navigation() -> None:
    """Expected to fail before the M07 browser implementation is integrated."""
    assets = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(STATIC.iterdir())
        if path.suffix in {".html", ".js", ".css", ".md"}
    )
    assert 'data-level="route_map"' in assets
    assert 'data-level="detail_evidence"' in assets
    assert "Back to Route Map" in assets
    assert not re.search(r"\bLevel\s*3\b|PresentationLevel\.EVIDENCE", assets, re.IGNORECASE)
    assert "Back to Events" not in assets and "Back to Arcs" not in assets
