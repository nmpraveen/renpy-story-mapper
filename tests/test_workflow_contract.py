from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _active_goal_path(state: str) -> str:
    contract = re.search(
        r"- Active goal and task ledger: \[`(docs/storyboard-v2/GOAL\.md)`\]", state
    )
    assert contract, "PROJECT_STATE.md must link the active Phase 01 goal"
    return contract.group(1)


def test_fresh_context_contract_uses_ai_first_storyboard_authority() -> None:
    agents = _read("AGENTS.md")
    skill = _read(".agents/skills/renpy-milestone/SKILL.md")
    master_plan = _read("docs/MASTER_PLAN.md")
    state = _read("docs/PROJECT_STATE.md")
    goal = _read(_active_goal_path(state))

    assert "Use AI as the primary semantic game analyst" in agents
    assert "Deterministic code owns safe source recovery" in agents
    assert "Uncertain dynamic behavior must remain explicitly unresolved" in agents
    assert "Cloud AI is the default" in skill
    assert "Build a deterministic, source-grounded evidence index" in skill
    assert "Let AI profile unfamiliar game conventions" in skill
    assert "A native Codex goal is optional" in skill
    assert "explicitly requests one." in skill
    assert "AI-first with deterministic guardrails" in master_plan
    assert "AI is the primary semantic game analyst" in master_plan
    assert "Deterministic code is the guardrail and bookkeeper" in master_plan
    assert "AI is the primary semantic analyst" in goal
    assert "Deterministic code is the guardrail" in goal


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
    assert state.count("- Active phase:") == 1
    assert "- Active phase: Phase 01 canary review." in state
    goal_path = _active_goal_path(state)
    assert (ROOT / goal_path).is_file()
    goal = _read(goal_path)
    assert goal.startswith("# AI-first storyboard Phase 01 canary")
    assert re.search(r"^Status: \S", goal, re.MULTILINE)
    assert "Native Codex goal: none" in state
    assert "default_prompt" in interface
