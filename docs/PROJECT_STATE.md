# Ren'Py Story Mapper project state

Updated: 2026-07-15

`docs/MASTER_PLAN.md` owns product scope. This file owns the operational pointer to one explicit milestone contract. Milestone-local files own acceptance and evidence.

## Current contract

- Active milestone: None.
- Contract: Not set.
- Status: Idle.
- Semantic review: Not started.
- Native Codex goal: None.
- Integration head: Not set.
- Pull request: Not set.

M11 is the latest completed product milestone. It merged through [PR #20](https://github.com/nmpraveen/renpy-story-mapper/pull/20) at commit `26502e88bd81b7a1934a6957724fd62f7ba5fbec` on 2026-07-15. No later product milestone is active or approved by this workflow change.

On explicit user approval of a milestone with a safe done condition, copy `docs/milestones/_TEMPLATE/` to the approved milestone directory, fill it from `docs/MASTER_PLAN.md`, and replace this section with links and current facts.

## State rules

1. Keep at most one active milestone contract and, after the user explicitly starts it, one matching native goal.
2. Use these transitions: `Draft -> Semantic review -> Ready -> In progress -> Integration -> Verification -> PR ready -> Complete`.
3. Use `Revise` when semantic review fails; return to `Semantic review` after correction. Use `Blocked` only with a recorded blocker and resume at the interrupted stage.
4. Require a recorded semantic-review `PASS` before broad implementation.
5. Keep the native goal active until the integrated change meets acceptance, required evidence and review are complete, and the PR is genuinely ready.
6. Update this pointer in the same integration that changes milestone status. Do not infer state from branch names or conversations.

## Authority order

1. User's explicit milestone approval and constraints.
2. `docs/MASTER_PLAN.md` for permanent product scope and exclusions.
3. Active milestone `GOAL.md` for the bounded contract.
4. Active milestone `SEMANTIC_REVIEW.md`, `TASKS.md`, and `COMPLETION_REPORT.md` for decision, execution, and evidence state.
5. This file for the current pointer and lifecycle state.

If these disagree, stop broad implementation, set the semantic decision to `REVISE`, and reconcile the higher authority without inventing scope.
