"""Generic prompt envelopes and schema locations for Phase 01 storyboard analysis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

PROFILE_PROMPT_VERSION = "storyboard-game-profile-prompt-v1"
ANALYSIS_PROMPT_VERSION = "storyboard-story-analysis-prompt-v2"
REPAIR_PROMPT_VERSION = "storyboard-canonical-repair-prompt-v1"
VALIDATION_REPAIR_PROMPT_VERSION = "storyboard-validation-repair-prompt-v1"
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
            "replay patterns. Include the game/story title when the evidence establishes it. "
            "Every inferred record must cite one or more exact evidence IDs."
        ),
        "authority": (
            "Evidence IDs and source text are authoritative. You may interpret unfamiliar "
            "syntax. The compact evidence_index records collection contains every ledger leaf "
            "and annotation exactly once; role identifies which kind, source_text is the exact "
            "text, and shared source provenance is stored once at the evidence-index level. "
            "Do not present an uncertain dynamic behavior as a fact. Preserve a "
            "confidence level and required status/uncertainty fields for each inference object; "
            "status=resolved requires uncertainty=null. status in uncertain, unresolved, or "
            "excluded requires a non-empty uncertainty string. Do not emit an unresolved string "
            "substitute. Embedded "
            "Python and runtime-computed behavior are unresolved by default. Custom or unknown "
            "constructs may be interpreted when the cited evidence supports the interpretation and "
            "the response supplies a rationale."
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
            "destinations, semantic destination scene IDs, explicit source/target evidence, "
            "rejoins, loops, terminals, and unresolved dynamic behavior. Include exact-once leaf "
            "ownership for shared scene bodies, each menu/conditional arm, shared continuations, "
            "and explicit exclusion/unresolved buckets. Use line_evidence_ids as the only direct "
            "source-line membership field for scenes, arms, and continuations; include it even "
            "when the list is empty. Preserve the declared scene order. Semantic evidence_ids "
            "are citations for claim grounding only: edge source/target binding must use only "
            "line_evidence_ids plus deterministic annotations physically associated with those "
            "member lines."
        ),
        "authority": (
            "Use the game profile for interpretation, but keep every structural or semantic "
            "claim bound to exact evidence IDs. The compact evidence_index records collection "
            "contains every ledger leaf and annotation exactly once; role identifies which kind, "
            "source_text is exact, and shared source provenance is stored at the index level. "
            "Do not invent or relocate source lines, choice "
            "arms, conditions, effects, destinations, rejoins, loops, or endings. If parser "
            "and interpretation disagree, record the disagreement explicitly. Every scene, "
            "choice, arm, consequence object, transition, continuation, claim, unresolved item, "
            "exclusion, and disagreement must have status plus nullable uncertainty; never use a "
            "legacy unresolved string. status=resolved requires uncertainty=null. status in "
            "uncertain, unresolved, or excluded requires a non-empty uncertainty string. Keep "
            "choices and transitions at the top level only. Use "
            "semantic destination_scene_id/rejoin_scene_id fields, and when a concrete destination "
            "is present include both source_evidence_ids and target_evidence_ids. If an arm claims "
            "both destination_scene_id and rejoin_scene_id, bind each edge separately with "
            "destination_source_evidence_ids/destination_target_evidence_ids and "
            "rejoin_source_evidence_ids/rejoin_target_evidence_ids; aggregate evidence must not "
            "stand in for either target. Line lists may be empty when a scene or arm has no direct "
            "lines. Semantic evidence_ids must never "
            "expand scene or arm edge-binding scope; use only line_evidence_ids and annotations "
            "physically associated with those member lines. Do not use any alternate membership "
            "field or replay envelope. The evidence_index physical_ownership map is authoritative "
            "for source-line membership only. Put every shared_line_evidence_id exactly once in a "
            "scene, continuation, or explicit owning unresolved/exclusion bucket. For every "
            "physical branch, create an arm whose evidence_ids cites branch_evidence_id and whose "
            "line_evidence_ids exactly equals that branch's line_evidence_ids; nested conditions "
            "need their own arm and must not be folded into an enclosing menu arm. Never repeat "
            "branch-owned lines in a scene body. Scene order is zero-based and contiguous. A "
            "destination_scene_id or rejoin_scene_id may reference only an ID declared in scenes, "
            "never a continuation ID; associate a continuation with its declared scene_id instead."
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


def build_canonical_repair_request(
    *,
    kind: str,
    prior_response: Mapping[str, object],
    validator_issues: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Build the sole targeted repair request for a canonical response mismatch."""

    if kind not in {"game-profile", "story-analysis"}:
        raise ValueError("kind must be game-profile or story-analysis")
    contract = PROFILE_SCHEMA_ID if kind == "game-profile" else ANALYSIS_SCHEMA_ID
    return {
        "prompt_version": REPAIR_PROMPT_VERSION,
        "task": (
            "Correct only the listed canonical validator failures in the prior response. Return "
            "the complete corrected JSON object. Do not coerce, normalize, delete, suppress, or "
            "reinterpret any otherwise valid field, citation, or semantic claim."
        ),
        "authority": (
            "The canonical Draft 2020-12 schema remains authoritative. status=resolved requires "
            "uncertainty=null. status in uncertain, unresolved, or excluded requires a non-empty "
            "uncertainty string. This is the only repair attempt; every listed failure must be "
            "corrected explicitly."
        ),
        "security": (
            "Use only the prior response and validator findings in this request; do not use "
            "tools, files, web, or outside knowledge."
        ),
        "input": {
            "validator_issues": [dict(issue) for issue in validator_issues],
            "prior_response": dict(prior_response),
        },
        "output_contract": {
            "schema": contract,
            "return": "one complete corrected JSON object matching the supplied schema",
        },
    }


def build_validation_repair_request(
    *,
    kind: str,
    prior_response: Mapping[str, object],
    validator_issues: Sequence[Mapping[str, object]],
    physical_ownership: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the sole response-level repair request after deterministic validation."""

    if kind not in {"game-profile", "story-analysis"}:
        raise ValueError("kind must be game-profile or story-analysis")
    contract = PROFILE_SCHEMA_ID if kind == "game-profile" else ANALYSIS_SCHEMA_ID
    repair_input: dict[str, object] = {
        "validator_issues": [dict(issue) for issue in validator_issues],
        "prior_response": dict(prior_response),
    }
    if physical_ownership is not None:
        repair_input["physical_ownership"] = dict(physical_ownership)
    return {
        "prompt_version": VALIDATION_REPAIR_PROMPT_VERSION,
        "task": (
            "Correct every listed deterministic validator failure in the prior response and "
            "return one complete corrected JSON object. Rebuild physical line membership from "
            "the supplied ownership map instead of moving individual examples heuristically. "
            "Do not delete, suppress, normalize, or silently reinterpret otherwise valid claims."
        ),
        "authority": (
            "The canonical Draft 2020-12 schema and deterministic physical_ownership map remain "
            "authoritative. Each accountable line must have exactly one owner. Shared lines cannot "
            "appear in arms; branch lines must appear only in the arm citing that "
            "branch_evidence_id. Scene order is zero-based and contiguous. Destination and rejoin "
            "IDs must name declared "
            "scenes, not continuations. Any object citing embedded Python or runtime-computed "
            "evidence must remain unresolved with a non-empty uncertainty. This is the only "
            "response-level repair attempt."
        ),
        "security": (
            "Use only the prior response, validator findings, and physical ownership facts in this "
            "request; do not use tools, files, web, or outside knowledge."
        ),
        "input": repair_input,
        "output_contract": {
            "schema": contract,
            "return": "one complete corrected JSON object matching the supplied schema",
        },
    }


def schema_path(kind: str) -> Path:
    """Return the packaged schema path for a supported storyboard call."""

    if kind == "game-profile":
        return GAME_PROFILE_SCHEMA_PATH
    if kind == "story-analysis":
        return STORY_ANALYSIS_SCHEMA_PATH
    raise ValueError("kind must be game-profile or story-analysis")
