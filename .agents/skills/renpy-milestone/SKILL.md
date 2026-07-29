---
name: renpy-milestone
description: Keep the active Ren'Py Story Mapper work aligned with the current user-visible story outcome.
---

# Ren'Py milestone

## Read current authority

Before milestone work, read:

1. repository-root `AGENTS.md`;
2. `docs/MASTER_PLAN.md`;
3. `docs/PROJECT_STATE.md`; and
4. the active `GOAL.md` linked from project state.

The user's latest explicit instruction overrides stale repository prose. If the active files conflict
with the user, update the files before product implementation. Historical milestone files are evidence,
not current rules.

## Keep the contract small

The active goal should state only:

- the real user outcome;
- the first real-game proof;
- the smallest implementation needed;
- clear exclusions; and
- observable acceptance checks.

Do not add arbitrary group counts, context limits, provider ceremonies, schema work, exhaustive test
matrices, CI, Release, packaging, PR, or infographic requirements unless the user asks for them or a
demonstrated blocker requires them. A native Codex goal is optional and is created only when the user
explicitly requests one.

## Execute progressively

For story work:

1. Build factual execution flow and state provenance in Python.
2. Prove it on one real story section.
3. Let AI summarize the Python-built corridors.
4. Show the rendered section to the user.
5. Apply it to the full game only after the proof is useful.

Cloud AI is the default; use a local LLM only when the user explicitly requests it. Trusted game
execution is allowed and should be headless when possible. Original inputs stay read-only.

## Parallel work

Here, a Codex task/thread means a separate user-visible task created through the Codex app's
thread/task tools and shown in the sidebar, not an internal subagent. When the user asks for tasks or
threads, never substitute subagents. When there are independent things to explore or implement,
dispatch separate user-visible `gpt-5.6-sol` High tasks unless the user selects other settings. For
bulk cloud summaries, inspect the first 10 results in the coordinator, then split the remainder
approximately evenly across three or four user-visible Sol/High tasks.

## Validate the outcome

Use focused checks while editing. Judge success from the real desktop scrolling timeline: correct
story order, branch membership, nesting, conditions, state back-links, destinations, and rejoins.
Broader CI, Release, packaging, reviews, and PR work wait until the user accepts the product result or
asks to ship it.

Update `PROJECT_STATE.md`, `GOAL.md`, and `TASKS.md` when the actual outcome or next action changes.
Do not copy historical operational logs into those files.
