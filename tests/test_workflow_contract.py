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
    assert "Active milestone: M13 - Optional AI narrative layer" in state
    assert any(
        f"- Status: {status}." in state
        for status in ("In progress", "Integration", "Verification", "PR ready")
    )
    assert "Semantic review: [`PASS`]" in state
    assert "docs/milestones/M13/GOAL.md" in state
    assert "PR #22" in state
    assert "f67df8a7cb805bf4adf8590585bae700d2f3117f" in state
    assert "default_prompt" in interface
