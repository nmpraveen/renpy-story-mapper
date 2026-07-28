from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_fresh_context_contract_has_one_gate_and_safe_goal_start() -> None:
    agents = _read("AGENTS.md")
    skill = _read(".agents/skills/renpy-milestone/SKILL.md")
    semantic_template = _read("docs/milestones/_TEMPLATE/SEMANTIC_REVIEW.md")

    assert "Follow the skill's single early semantic-review gate" in agents
    assert skill.count("authoritative early gate") == 1
    assert "Create a native Codex goal only when all of these are true" in skill
    assert "The user explicitly starts this approved milestone" in skill
    assert "one safe, observable done condition" in skill
    assert "`PASS` or `REVISE`" in semantic_template


def test_fresh_context_dispatch_and_current_lifecycle_are_explicit() -> None:
    agents = _read("AGENTS.md")
    state = _read("docs/PROJECT_STATE.md")
    interface = _read(".agents/skills/renpy-milestone/agents/openai.yaml")

    for value in ("gpt-5.6-sol", "Medium reasoning", "fast mode disabled"):
        assert value in agents
    assert "The user selects the coordinator and worker model" in agents
    assert "QUICK, CRUDE SCRIPT-TO-STORY CHECKER" in agents
    assert "Repository prose cannot change Codex client settings" in agents
    assert state.count("- Active milestone:") == 1
    assert "Active milestone: M15.1 Phase 05" in state
    assert "- Status: Integration." in state
    assert "Semantic review: `PASS`" in state
    assert "docs/milestones/M15_PHASE_05/GOAL.md" in state
    assert "Native Codex goal: active" in state
    assert "268d30ed15d50136be5a88d464f79adaf7f32f9e" in state
    assert "gpt-5.6-sol" in state
    assert "High reasoning" in state
    assert "no new Ultra task may be dispatched" in state
    assert "fast mode remains unavailable/unverified" in state
    assert "docs/MILESTONE_PLANNING_RULES.md" in state
    assert "default_prompt" in interface
