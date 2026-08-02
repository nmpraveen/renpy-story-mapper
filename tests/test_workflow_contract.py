from __future__ import annotations

import re
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
    # A fresh context must be able to read the current lifecycle off PROJECT_STATE.md.
    # Pinning the literal milestone made this a snapshot that went stale at every bump and
    # still passed while the contract link rotted, so require the declaration to be present
    # and self-consistent instead: exactly one active milestone, a contract that names the
    # same phase and exists on disk, a checkout on that phase, and a stated status.
    assert state.count("- Active milestone:") == 1
    milestone = re.search(r"- Active milestone: M\d+(?:\.\d+)? Phase (\d+)\b", state)
    assert milestone, "PROJECT_STATE.md must name the active milestone as 'M<n> Phase <nn>'"
    phase = milestone.group(1)
    contract = re.search(r"- Contract: \[`(docs/milestones/[^`]+/GOAL\.md)`\]", state)
    assert contract, "PROJECT_STATE.md must link the active milestone contract"
    assert f"PHASE_{phase}" in contract.group(1)
    assert (ROOT / contract.group(1)).is_file()
    assert re.search(rf"- Active checkout: `[^`]*phase{phase}[^`]*`", state)
    assert re.search(r"^- Status: \S", state, re.MULTILINE)
    assert "Native Codex goal: none" in state
    assert "default_prompt" in interface
