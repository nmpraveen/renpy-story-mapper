---
name: renpy-milestone
description: Execute or review one bounded Ren'Py Storyboard milestone using AI-first semantic analysis and deterministic evidence and coverage checks. Use for milestone implementation or review, not general repository questions.
---

# Ren'Py Storyboard milestone

## Read current authority

Before milestone work, read:

1. repository-root `AGENTS.md`;
2. `docs/MASTER_PLAN.md`;
3. `docs/PROJECT_STATE.md`;
4. the active `GOAL.md`; and
5. the active `TASKS.md`, when present.

The user's latest explicit instruction overrides stale repository prose. Update active authority
files only when the actual product outcome, phase, or next action changes. Historical milestone
files are evidence, not current rules.

## Keep the contract bounded

The active phase should state only:

- the user-visible outcome;
- the bounded real-game proof;
- the smallest implementation required;
- explicit exclusions; and
- observable acceptance checks.

Do not add a provider platform, workflow framework, database, fixed model or task counts, arbitrary
batch counts, broad CI, release work, packaging, PR ceremony, or legacy cleanup unless the user
requests it or a demonstrated blocker requires it.

## Execute AI-first with deterministic guardrails

For story work:

1. Preserve a source-grounded evidence ledger before semantic analysis. Parser failure may reduce
   deterministic annotations but must not hide the raw source from AI.
2. Use AI as the primary semantic analyst for unfamiliar game conventions, scenes, characters,
   choices, consequences, routes, endings, hidden content, and custom mechanics.
3. Require exact evidence references, confidence, and explicit uncertainty for AI-derived claims.
   Keep parser/AI disagreements visible.
4. Use deterministic code to validate evidence identity, references, structural parentage,
   per-scene and per-branch ownership, omissions, duplication, and unresolved behavior.
5. Use one canonical evidence contract and one canonical story-analysis contract across AI,
   validation, replay, and rendering.
6. Prove the approach on one bounded real story section and inspect the rendered result before
   scaling to the full game.
7. Stop at the active phase boundary and report limitations honestly.

## Inputs and execution

Keep original game inputs read-only. Do not expose absolute local paths in AI or public artifacts.
Do not execute game code unless the user explicitly authorizes it and execution is isolated,
headless where practical, and treated as untrusted.

Cloud AI is the default unless the user requests another arrangement. AI failure must not be
converted into a confident structural claim.

## Parallel work

Use separate user-visible Codex tasks only when the work is genuinely independent and parallel
execution materially helps. Follow repository `AGENTS.md` for task settings. Do not prescribe a
fixed model, number of tasks, batch count, or canary size in this reusable skill. The coordinating
task owns scope, integration, and final validation.

## Keep the Workflow Atlas current

For coordinated work, only the active-phase coordinator may edit or publish the Workflow Atlas.
Workers report their node or workstream, status, evidence or commit, and safe failure summary to the
coordinator. The coordinator updates accepted plans, execution starts, material gate transitions,
and final outcomes. A coordinated phase is not complete until the final Atlas state is published or
publication is explicitly reported as blocked.

## Validate the outcome

Use focused checks while editing and inspect the real generated artifact. Judge success from story
order, scene and branch ownership, nesting, exact choices and conditions, consequences, state
dependencies, destinations, rejoins, loops, endings, unresolved behavior, source traceability, and
normal-reader clarity.

Broader CI, release, packaging, and legacy cleanup wait until the user accepts the product result or
explicitly asks to ship it.
