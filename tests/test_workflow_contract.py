from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _active_goal_path(state: str) -> str:
    contract = re.search(r"- Contract: \[`(docs/milestones/[^`]+/GOAL\.md)`\]", state)
    assert contract, "PROJECT_STATE.md must link the active milestone contract"
    return contract.group(1)


def test_fresh_context_contract_uses_progressive_story_authority() -> None:
    agents = _read("AGENTS.md")
    skill = _read(".agents/skills/renpy-milestone/SKILL.md")
    master_plan = _read("docs/MASTER_PLAN.md")
    state = _read("docs/PROJECT_STATE.md")
    goal = _read(_active_goal_path(state))

    assert "Build the story progressively from Ren'Py execution flow" in agents
    assert "Python owns factual structure" in agents
    assert "AI may name, summarize, explain, and editorially group" in agents
    assert "Cloud AI is the default" in agents
    assert "Build factual execution flow and state provenance in Python" in skill
    assert "A native Codex goal is optional" in skill
    assert "explicitly requests one." in skill
    assert "execution-derived corridors define story units" in master_plan
    assert (
        "deterministic Python builds and freezes factual execution/state structure" in master_plan
    )
    assert "Keep deterministic parsing, control flow, state provenance" in goal
    assert "Keep AI output in a strict editorial-only schema" in goal


def test_fresh_context_dispatch_and_current_lifecycle_are_explicit() -> None:
    agents = _read("AGENTS.md")
    state = _read("docs/PROJECT_STATE.md")
    interface = _read(".agents/skills/renpy-milestone/agents/openai.yaml")

    for value in ("gpt-5.6-sol", "High reasoning", "user-visible Codex tasks"):
        assert value in agents
    assert "Never substitute internal subagents" in agents
    for stale in ("Medium reasoning", "fast mode disabled", "QUICK, CRUDE"):
        assert stale not in agents
    # A fresh context must be able to follow the current lifecycle from PROJECT_STATE.md.
    # Milestones may use a phase suffix, but the linked goal remains the source of status.
    assert state.count("- Active milestone:") == 1
    milestone = re.search(r"- Active milestone: (M\d+(?:\.\d+)?)(?: Phase \d+)?\b", state)
    assert milestone, "PROJECT_STATE.md must name the active milestone as M<n>"
    goal_path = _active_goal_path(state)
    assert f"/milestones/{milestone.group(1)}" in f"/{goal_path}"
    assert (ROOT / goal_path).is_file()
    goal = _read(goal_path)
    assert goal.startswith(f"# {milestone.group(1)}")
    assert re.search(r"^Status: \S", goal, re.MULTILINE)
    assert "Native Codex goal: none" in state
    assert "default_prompt" in interface
