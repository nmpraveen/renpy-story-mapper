from __future__ import annotations

import json
from importlib.resources import files

from renpy_story_mapper.narrative_map.provider import SEMANTIC_BOUNDARY_PROMPT_VERSION


def test_boundary_prompt_uses_selective_editorial_hierarchy_policy() -> None:
    assert SEMANTIC_BOUNDARY_PROMPT_VERSION == "m15-semantic-boundary-prompt-v3"
    resource = files("renpy_story_mapper.narrative_map.prompts").joinpath(
        "semantic_boundary_v3.json"
    )
    prompt = json.loads(resource.read_text(encoding="utf-8"))

    assert prompt["version"] == SEMANTIC_BOUNDARY_PROMPT_VERSION
    decisions = prompt["decisions"]
    assert set(decisions) == {
        "same_beat",
        "new_beat_same_cluster",
        "new_major_cluster",
        "uncertain",
    }
    assert "one immediate" in decisions["same_beat"]
    assert "Use this selectively" in decisions["new_beat_same_cluster"]
    assert "Reserve this" in decisions["new_major_cluster"]
    assert "insufficient" in decisions["uncertain"]

    policy = json.dumps(prompt, sort_keys=True)
    for technical_cue in ("image", "music", "hint", "screen", "menu"):
        assert technical_cue in policy
    for routing_cue in ("choice", "arm", "rejoin"):
        assert routing_cue in policy
    assert "trailing day/chapter marker" in policy
    assert "no following event in scope" in policy


def test_prior_boundary_prompt_remains_packaged_for_historical_identity() -> None:
    prior = files("renpy_story_mapper.narrative_map.prompts").joinpath(
        "semantic_boundary_v2.json"
    )
    assert json.loads(prior.read_text(encoding="utf-8"))["version"] == (
        "m15-semantic-boundary-prompt-v2"
    )
