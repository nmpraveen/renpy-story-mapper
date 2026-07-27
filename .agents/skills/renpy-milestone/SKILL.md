---
name: renpy-milestone
description: Maintain and execute one evidence-backed Ren'Py Story Mapper milestone contract. Use when starting, planning, implementing, integrating, reviewing, handing off, verifying, or closing a repository milestone, or when updating its goal, task ledger, semantic review, acceptance evidence, project state, or PR readiness.
---

# Ren'Py milestone

## Apply the simplicity gate first

The repository's product is a quick, crude script-to-story checker, not a production-grade system.
Before adding a deliverable, acceptance criterion, worker, review, schema, protocol, persistence
rule, recovery case, or scale test, answer all three questions:

1. Does it directly help the user load the current Ren'Py game and understand its rough story,
   choices, routes, important state changes, or rejoins?
2. Is it required by a demonstrated blocker in the current end-to-end workflow?
3. Is there no smaller use of the existing code that is good enough for quick checking?

If the answer to any question is no or uncertain, do not add the work. Pause the milestone and ask
the user. Historical contracts and already-written complex code do not create a requirement to
finish that complexity.

## Establish authority

1. Read repository-root `AGENTS.md`, `docs/MASTER_PLAN.md`, and `docs/PROJECT_STATE.md`.
2. Follow the active contract linked by `docs/PROJECT_STATE.md`. Treat `GOAL.md` as the approved milestone contract and `MASTER_PLAN.md` as scope authority.
3. Keep exactly one active contract. Never infer milestone approval from a branch, issue, or old report.
4. If the user explicitly starts an approved milestone and no contract exists, copy `docs/milestones/_TEMPLATE/` to its milestone directory. Fill it only from approved scope. Do not turn likely architecture, prior-milestone conventions, or desirable checks into new acceptance criteria; ask for approval when the done condition cannot be stated safely.
5. Read `docs/MILESTONE_PLANNING_RULES.md` and apply its outcome-first scope, orchestration, model,
   quota, review, and test rules.

## Lock the contract

Before product implementation, make `GOAL.md` contain one explicit done condition, deliverables, numbered acceptance criteria, exclusions, evidence requirements, and handoff rules. Make `TASKS.md` name owners, dependencies, affected area, and status.

Keep the contract lean: one real user outcome, three to five implementation gates, and only the
minimum acceptance criteria needed to prove that outcome. Record non-goals explicitly. Do not turn
production hardening, theoretical scale, perfect reproducibility, or exhaustive fault handling
into acceptance unless the user explicitly requests it.

Create a native Codex goal only when all of these are true:

- The user explicitly starts this approved milestone; approval, a branch, an issue, or a request to inspect or plan is not enough.
- The contract has one safe, observable done condition that does not invent scope.
- The goal objective exactly matches that done condition.

Create it before changing product code. Keep it active if the later semantic decision is `REVISE`.

After creation:

- Record the goal in `docs/PROJECT_STATE.md` and keep it active through implementation, integration, verification, review, and PR preparation.
- Do not complete the goal merely because code is authored, a worker committed, checks are planned, or a handoff was sent. Complete it only after the integrated diff satisfies acceptance, evidence is recorded, blocking review findings are resolved or explicitly accepted, required checks pass, and the PR is genuinely ready.

If approved scope is too incomplete to state a done condition without invention, record `REVISE`, request the missing scope decision, and do not claim implementation has started or create a guessed goal.

## Pass the single semantic-review gate

This section is the authoritative early gate. Before broad implementation, fill `SEMANTIC_REVIEW.md` from repository evidence:

- Verify each requirement against the approved plan and exclusions.
- Identify architecture authority and boundaries, including code that must not change.
- List expected files or components and focused, regression, integration, and acceptance checks.
- Map every acceptance criterion to evidence that can prove it.
- Record assumptions, conflicts, and unresolved decisions.
- End with exactly `PASS` or `REVISE`, plus rationale.

Treat a requirement or architecture choice that would materially change the done condition as a scope decision, not an implementation assumption.

Permit only read-only discovery, narrow experiments, and contract edits before `PASS`. On `REVISE`, stop broad implementation, resolve the contract problem, and repeat the gate.

## Execute and record evidence

1. Move the state through `Draft -> Semantic review -> Ready -> In progress -> Integration -> Verification -> PR ready -> Complete`. Use `Revise` from the gate and `Blocked` only with a recorded blocker. Resume at the prior stage after resolution.
2. Update `TASKS.md` at real transitions. Do not use it as the only acceptance record.
3. Attach command, result, artifact, commit, or review evidence to each acceptance criterion. Mark unknown or unavailable evidence honestly.
4. Preserve milestone exclusions and repository safety rules during delegation and integration.
5. Update `docs/PROJECT_STATE.md` whenever the active contract, stage, semantic decision, native goal, integration head, or PR state changes.
6. Use one user-visible Orchestra task. Dispatch no more than two independent workers at once by
   default. The user must choose the model and reasoning settings for each phase or resumption;
   never silently inherit or escalate them.
7. The Orchestra checks only useful completion or decision checkpoints. It does not continuously
   poll commentary, wait on healthy CI, or spawn speculative correction loops.
8. During implementation, run affected tests and direct static checks. Run one focused integrated
   gate at a meaningful checkpoint, repository sharded CI at the PR-candidate boundary, and one
   full Windows Release/package gate on the final intended head unless the contract explicitly
   requires more.
9. If implementation needs a new architecture layer, schema version, protocol family, extensive
   recovery matrix, extra review tier, or more than one correction loop, pause and ask whether it
   is truly necessary for the real user outcome.

## Handoff and close

For every worker handoff, require the exact commit, worktree or branch, changed files, checks with results, assumptions, known defects, conflicts, and remaining acceptance work. Keep the milestone in `Integration` until the work is actually integrated.

Before `PR ready`:

- Review the integrated diff against the contract and exclusions.
- Run the contract's focused and regression checks, then required repository and acceptance checks.
- Resolve or explicitly accept review findings at the allowed severity.
- Fill `COMPLETION_REPORT.md` with acceptance evidence, validation results, integration commit, remaining limitations, and PR state.
- Prepare or open the single milestone PR as the user's instructions require.

One early semantic review and one final integrated review are the default. Per-worker exact-head
review, exhaustive fault injection, and repeated full-suite or Release runs are not default
milestone requirements.

Set the native goal complete only at genuine `PR ready`. Set the repository state to `Complete` after merge and state reconciliation. Leave evidence paths durable and make the handoff self-contained.
