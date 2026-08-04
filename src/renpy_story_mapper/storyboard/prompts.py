"""Generic prompt envelopes and schema locations for Phase 01 storyboard analysis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

PROFILE_PROMPT_VERSION = "storyboard-game-profile-prompt-v1"
ANALYSIS_PROMPT_VERSION = "storyboard-story-analysis-prompt-v1"
PROFILE_SCHEMA_ID = "storyboard-game-profile-v1"
ANALYSIS_SCHEMA_ID = "storyboard-story-analysis-v1"

GAME_PROFILE_SCHEMA_PATH = Path(__file__).with_name("schemas") / "game-profile.schema.json"
STORY_ANALYSIS_SCHEMA_PATH = Path(__file__).with_name("schemas") / "story-analysis.schema.json"


def build_game_profile_request(
    *, evidence_index: Mapping[str, object]
) -> dict[str, object]:
    """Build one bounded reconnaissance request without game-specific assumptions."""

    return {
        "prompt_version": PROFILE_PROMPT_VERSION,
        "task": (
            "Infer the conventions needed to explain this Ren'Py source. Identify characters, "
            "variables, custom constructs, scene conventions, entry points, and ending or "
            "replay patterns. Every inferred record must cite one or more exact evidence IDs."
        ),
        "authority": (
            "Evidence IDs and source text are authoritative. You may interpret unfamiliar "
            "syntax, but do not present an uncertain dynamic behavior as a fact. Preserve a "
            "confidence level and an unresolved explanation for each inference."
        ),
        "security": (
            "Use only the structured evidence in this request; do not use tools, files, web, "
            "or outside knowledge."
        ),
        "input": {"evidence_index": dict(evidence_index)},
        "output_contract": {
            "schema": PROFILE_SCHEMA_ID,
            "return": "one JSON object matching the supplied schema",
        },
    }


def build_story_analysis_request(
    *,
    evidence_index: Mapping[str, object],
    game_profile: Mapping[str, object],
    canary_evidence_ids: Sequence[str],
) -> dict[str, object]:
    """Build one canary analysis request bound to the generated game profile."""

    return {
        "prompt_version": ANALYSIS_PROMPT_VERSION,
        "task": (
            "Explain the selected connected story section as a readable storyboard. Preserve "
            "exact-line membership by evidence ID, choices, conditions, branch consequences, "
            "destinations, rejoins, loops, terminals, and unresolved dynamic behavior."
        ),
        "authority": (
            "Use the game profile for interpretation, but keep every structural or semantic "
            "claim bound to exact evidence IDs. Do not invent or relocate source lines, choice "
            "arms, conditions, effects, destinations, rejoins, loops, or endings. If parser and "
            "interpretation disagree, record the disagreement explicitly."
        ),
        "security": (
            "Use only the structured profile and evidence in this request; do not use tools, "
            "files, web, or outside knowledge."
        ),
        "input": {
            "evidence_index": dict(evidence_index),
            "game_profile": dict(game_profile),
            "canary_evidence_ids": list(canary_evidence_ids),
        },
        "output_contract": {
            "schema": ANALYSIS_SCHEMA_ID,
            "return": "one JSON object matching the supplied schema",
        },
    }


def schema_path(kind: str) -> Path:
    """Return the packaged schema path for a supported storyboard call."""

    if kind == "game-profile":
        return GAME_PROFILE_SCHEMA_PATH
    if kind == "story-analysis":
        return STORY_ANALYSIS_SCHEMA_PATH
    raise ValueError("kind must be game-profile or story-analysis")
