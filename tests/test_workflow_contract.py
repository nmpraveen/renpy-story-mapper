from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _active_goal_path(state: str) -> str:
    contract = re.search(
        r"- Active goal and task ledger: \[`(docs/storyboard-v2/GOAL\.md)`\]",
        state,
    )
    assert contract, "PROJECT_STATE.md must link the active Phase 01 goal"
    return contract.group(1)


def _authority_items(state: str) -> list[str]:
    _, heading, authority = state.partition("## Authority")
    assert heading, "PROJECT_STATE.md must document the authority chain"
    return re.findall(r"(?m)^\d+\.\s+(.+)$", authority)


def test_active_authority_chain_and_goal_are_resolvable() -> None:
    state = _read("docs/PROJECT_STATE.md")
    goal_path = _active_goal_path(state)

    assert (ROOT / goal_path).is_file()
    authority = _authority_items(state)
    assert len(authority) >= 4
    assert re.search(r"user.+latest explicit instruction", authority[0], re.IGNORECASE)
    assert "AGENTS.md" in authority[1]
    assert "MASTER_PLAN.md" in authority[1]
    assert "goal" in authority[2].lower()
    assert "project-state" in authority[3].lower()


def test_reusable_skill_requires_ai_first_analysis_with_deterministic_guardrails() -> None:
    skill = _read(".agents/skills/renpy-milestone/SKILL.md")

    assert "Use AI as the primary semantic analyst" in skill
    assert re.search(
        r"Parser failure.+must not hide the raw source from AI",
        skill,
        re.DOTALL,
    )
    assert re.search(
        r"deterministic code.+per-scene and per-branch ownership",
        skill,
        re.DOTALL,
    )
    assert "one canonical evidence contract" in skill
    assert "one canonical story-analysis contract" in skill


def test_reusable_skill_has_no_project_specific_games_models_or_work_counts() -> None:
    skill = _read(".agents/skills/renpy-milestone/SKILL.md")
    stale_literals = (
        "Ms. Denvers",
        "Resort of Temptation",
        "Terrance",
        "gpt-5.6-sol",
        "Luna/Max",
        "Sol/High",
        "first 10",
        "first ten",
        "three or four",
    )

    for stale in stale_literals:
        assert stale.casefold() not in skill.casefold()


def test_project_state_has_one_active_phase_and_live_goal() -> None:
    state = _read("docs/PROJECT_STATE.md")
    goal = _read(_active_goal_path(state))
    interface = _read(".agents/skills/renpy-milestone/agents/openai.yaml")

    active_phases = re.findall(r"(?m)^- Active phase:\s*(\S.+?)\s*$", state)
    assert len(active_phases) == 1
    assert re.search(r"^Status: \S", goal, re.MULTILINE)
    assert "default_prompt" in interface


def test_workflow_atlas_has_coordinator_only_publication_authority() -> None:
    agents = _read("AGENTS.md")
    state = _read("docs/PROJECT_STATE.md")
    skill = _read(".agents/skills/renpy-milestone/SKILL.md")

    assert "sole authority" in agents
    assert "Worker tasks must not modify the Atlas" in agents
    assert "sole Workflow Atlas publisher" in state
    assert "only the active-phase coordinator may edit or publish" in skill
