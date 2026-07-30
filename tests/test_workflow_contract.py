from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_fresh_context_contract_uses_progressive_story_authority() -> None:
    agents = _read("AGENTS.md")
    skill = _read(".agents/skills/renpy-milestone/SKILL.md")
    master_plan = _read("docs/MASTER_PLAN.md")
    goal = _read("docs/milestones/M15_PHASE_05/GOAL.md")

    assert "Build the story progressively from Ren'Py execution flow" in agents
    assert "Python owns factual structure" in agents
    assert "AI may name, summarize, explain, and editorially group" in agents
    assert "Cloud AI is the default" in agents
    assert "Build factual execution flow and state provenance in Python" in skill
    assert "A native Codex goal is optional" in skill
    assert "explicitly requests one." in skill
    assert "progressive execution/state story walker" in " ".join(master_plan.split())
    assert "Python progressively builds the real execution and state flow" in goal


def test_fresh_context_dispatch_and_current_lifecycle_are_explicit() -> None:
    agents = _read("AGENTS.md")
    state = _read("docs/PROJECT_STATE.md")
    interface = _read(".agents/skills/renpy-milestone/agents/openai.yaml")

    for value in ("gpt-5.6-sol", "High reasoning", "user-visible Codex tasks"):
        assert value in agents
    assert "Never substitute internal subagents" in agents
    for stale in ("Medium reasoning", "fast mode disabled", "QUICK, CRUDE"):
        assert stale not in agents
    assert state.count("- Active milestone:") == 1
    assert "Active milestone: M15.1 Phase 05" in state
    assert "the clean-timeline goal remains open" in state
    assert "docs/milestones/M15_PHASE_05/GOAL.md" in state
    assert "Native Codex goal: none" in state
    assert "codex/m15-phase05-whole-game-skeleton" in state
    assert "default_prompt" in interface
