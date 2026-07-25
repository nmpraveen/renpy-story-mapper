from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from renpy_story_mapper.story_map_v2.contracts import (
    ArmLineageStep,
    ChunkExecutionResult,
    ChunkProfile,
    ChunkStatus,
    CoreBranchOutcome,
    CoreChunk,
    EventAnchor,
    ExecutionMode,
    ProviderOrigin,
    ProviderSettings,
    Reachability,
    RunPreview,
    StoryChunk,
    StoryMapCore,
    canonical_hash,
)
from story_map_v2_fixtures import arm, choice, span


def test_contracts_reject_non_contiguous_authoritative_arm_order() -> None:
    with pytest.raises(ValueError, match="contiguous"):
        value = choice()
        type(value)(
            key=value.key,
            relative_path=value.relative_path,
            line=value.line,
            arms=(value.arms[0], arm(3, "Wait", 30, 32, destination="node:wait")),
        )


def test_preview_confirmation_binds_mode_packets_and_settings() -> None:
    chunk = StoryChunk(
        index=1,
        span_keys=("s1",),
        choice_keys=(),
        raw_text="1: story",
        mechanics='{"choices":[]}',
        raw_tokens=2,
        density=value_density(),
        packet_hash="b" * 64,
    )
    preview = RunPreview(
        schema="story-map-v2-preview-v1",
        source_identity="source-v1",
        chunk_identities=(chunk.identity,),
        packet_hashes=(chunk.packet_hash,),
        payload_hashes=(chunk.payload_hash,),
        transmitted_fields=("raw_text", "mechanics"),
        prompt_version="prompt-v1",
        mapper_schema="story-map-v2-mapper-v1",
        mode=ExecutionMode.CLOUD_PRIMARY,
        cloud_settings=ProviderSettings(),
        allow_local_fallback=True,
        local_model="local-model",
        local_endpoint="http://127.0.0.1:1234/v1",
        maximum_hosted_planned=6,
        maximum_hosted_absolute=8,
        maximum_local=1,
        privacy_exclusions=("secrets", "evaluation material"),
    )
    changed = RunPreview(**{**preview.__dict__, "allow_local_fallback": False})
    changed_endpoint = RunPreview(
        **{**preview.__dict__, "local_endpoint": "http://127.0.0.1:5678/v1"}
    )
    assert preview.confirmation_hash != changed.confirmation_hash
    assert preview.confirmation_hash != changed_endpoint.confirmation_hash


def test_preview_payload_hash_binds_exact_provider_facing_chunk_content() -> None:
    chunk = StoryChunk(
        index=1,
        span_keys=("s1",),
        choice_keys=(),
        raw_text="1: original story",
        mechanics='{"choices":[]}',
        raw_tokens=3,
        density=value_density(),
        packet_hash="d" * 64,
    )
    changed_text = replace(chunk, raw_text="1: altered story")
    changed_mechanics = replace(chunk, mechanics='{"choices":[{"key":"altered"}]}')

    assert changed_text.packet_hash == chunk.packet_hash
    assert changed_mechanics.packet_hash == chunk.packet_hash
    assert changed_text.identity == chunk.identity
    assert changed_mechanics.identity == chunk.identity
    assert changed_text.payload_hash != chunk.payload_hash
    assert changed_mechanics.payload_hash != chunk.payload_hash


def test_default_limits_and_reachability_vocabulary_are_frozen() -> None:
    assert ChunkProfile() == ChunkProfile(8_000, 5_000, 10_700, 12)
    assert tuple(Reachability) == (
        Reachability.REACHABLE,
        Reachability.UNREACHABLE,
        Reachability.UNRESOLVED,
    )
    assert ArmLineageStep("choice:1", 1) < ArmLineageStep("choice:1", 2)


def test_source_span_carries_python_owned_reachability_and_warnings() -> None:
    value = span(
        "dynamic",
        20,
        24,
        100,
        reachability=Reachability.UNRESOLVED,
        warnings=("dynamic target",),
    )

    assert value.reachability is Reachability.UNRESOLVED
    assert value.unresolved_warnings == ("dynamic target",)


def test_story_chunk_retains_the_exact_compact_mechanics_packet() -> None:
    value = StoryChunk(
        index=1,
        span_keys=("s1",),
        choice_keys=("scripts/day.rpy:10",),
        raw_text="1: story",
        mechanics='{"choices":[{"key":"scripts/day.rpy:10"}]}',
        raw_tokens=2,
        density=value_density(),
        packet_hash="c" * 64,
    )

    assert value.mechanics == '{"choices":[{"key":"scripts/day.rpy:10"}]}'


def test_core_chunk_retains_mapper_scope_text_and_python_anchored_branch_outcome() -> None:
    anchor = EventAnchor(
        id="anchor-1",
        canonical_node_id="node:ridge",
        relative_path="scripts/day.rpy",
        line=11,
        arm_lineage=(ArmLineageStep("scripts/day.rpy:10", 1),),
        destination_id="node:ridge",
    )
    outcome = CoreBranchOutcome(
        choice_key="scripts/day.rpy:10",
        arm_order=1,
        caption="Take the ridge",
        summary="They choose the difficult route.",
        anchor=anchor,
        reachability=Reachability.REACHABLE,
    )
    chunk = CoreChunk(
        chunk_identity="chunk-1",
        status=ChunkStatus.COMPLETE,
        origin=ProviderOrigin.CLOUD,
        events=(),
        choices=(),
        branch_outcomes=(outcome,),
        scope_title="A difficult route",
        scope_overview="The group decides how to proceed.",
    )

    assert chunk.branch_outcomes == (outcome,)
    assert chunk.scope_title == "A difficult route"
    assert chunk.scope_overview == "The group decides how to proceed."
    core = StoryMapCore(
        schema="story-map-v2-core-v1",
        source_identity="source-1",
        status=ChunkStatus.COMPLETE,
        chunks=(chunk,),
        title=chunk.scope_title,
        overview=chunk.scope_overview,
    )
    assert core.title == "A difficult route"
    assert core.overview == "The group decides how to proceed."


def test_core_chunk_retains_exact_per_chunk_provider_provenance() -> None:
    execution = ChunkExecutionResult(
        chunk_identity="chunk-1",
        origin=ProviderOrigin.CLOUD,
        status=ChunkStatus.COMPLETE,
        response=None,
        failure_kind=None,
        elapsed_ms=25,
        response_hash="d" * 64,
        sanitized_reason=None,
        input_tokens=120,
        output_tokens=30,
        requested_model="gpt-5.6-luna",
        resolved_model="gpt-5.6-luna",
        reasoning="high",
        fast_mode=False,
    )
    chunk = CoreChunk(
        chunk_identity="chunk-1",
        status=ChunkStatus.COMPLETE,
        origin=ProviderOrigin.CLOUD,
        events=(),
        choices=(),
        execution=execution,
    )

    assert chunk.execution == execution
    assert chunk.execution.resolved_model == "gpt-5.6-luna"
    assert chunk.execution.reasoning == "high"
    assert chunk.execution.fast_mode is False


def test_story_map_v2_has_no_transitive_historical_semantic_dependency() -> None:
    root = Path(__file__).parents[1] / "src" / "renpy_story_mapper"
    package = root / "story_map_v2"
    forbidden = {
        "renpy_story_mapper.narrative",
        "renpy_story_mapper.narrative_map",
        "renpy_story_mapper.organization",
    }
    pending = list(package.rglob("*.py"))
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            names = [item.name for item in node.names] if isinstance(node, ast.Import) else []
            imports = ([module] if module else []) + names
            for imported in imports:
                assert not any(
                    imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden
                ), imported
                local = root.parent / Path(imported.replace(".", "/") + ".py")
                if imported.startswith("renpy_story_mapper.") and local.is_file():
                    pending.append(local)


def value_density():
    from renpy_story_mapper.story_map_v2.contracts import DensityMetrics

    return DensityMetrics()


def test_canonical_hash_is_stable_for_small_contract_values() -> None:
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})
