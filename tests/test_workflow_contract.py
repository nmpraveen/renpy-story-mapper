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

    for value in ("gpt-5.6-sol", "thinking `high`", "fast mode disabled"):
        assert value in agents
    assert "Repository prose cannot change Codex client settings" in agents
    assert state.count("- Active milestone:") == 1
    assert "Active milestone: M15.1 Phase 04" in state
    assert "- Status: In progress." in state
    assert "Semantic review: repeated exact-head `PASS`" in state
    assert "current P0=P1=P2=0" in state
    assert "docs/milestones/M15_PHASE_04/GOAL.md" in state
    assert "Native Codex goal: active on coordinator task" in state
    assert "019f7fe2-eeaa-7622-b3eb-f53d5bd5f749" in state
    assert "e715d8ae80dd1188c729a447cfabf3c45b3b7286" in state
    assert "a42e8a0" in state
    assert "default_prompt" in interface
