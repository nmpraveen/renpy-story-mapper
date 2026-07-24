from __future__ import annotations

import ast
from pathlib import Path

import pytest

from renpy_story_mapper.story_map_v2.contracts import (
    ArmLineageStep,
    ChunkProfile,
    ExecutionMode,
    ProviderSettings,
    Reachability,
    RunPreview,
    StoryChunk,
    canonical_hash,
)
from story_map_v2_fixtures import arm, choice


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
    chunk = StoryChunk(1, ("s1",), (), "1: story", 2, value_density(), "b" * 64)
    preview = RunPreview(
        schema="story-map-v2-preview-v1",
        source_identity="source-v1",
        chunk_identities=(chunk.identity,),
        packet_hashes=(chunk.packet_hash,),
        transmitted_fields=("raw_text", "mechanics"),
        prompt_version="prompt-v1",
        mapper_schema="story-map-v2-mapper-v1",
        mode=ExecutionMode.CLOUD_PRIMARY,
        cloud_settings=ProviderSettings(),
        allow_local_fallback=True,
        local_model="local-model",
        maximum_hosted_planned=6,
        maximum_hosted_absolute=8,
        maximum_local=1,
        privacy_exclusions=("secrets", "evaluation material"),
    )
    changed = RunPreview(**{**preview.__dict__, "allow_local_fallback": False})
    assert preview.confirmation_hash != changed.confirmation_hash


def test_default_limits_and_reachability_vocabulary_are_frozen() -> None:
    assert ChunkProfile() == ChunkProfile(8_000, 5_000, 10_700, 12)
    assert tuple(Reachability) == (
        Reachability.REACHABLE,
        Reachability.UNREACHABLE,
        Reachability.UNRESOLVED,
    )
    assert ArmLineageStep("choice:1", 1) < ArmLineageStep("choice:1", 2)


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
