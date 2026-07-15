# Ren'Py Story Mapper project state

Updated: 2026-07-15

`docs/MASTER_PLAN.md` owns product scope. This file owns the operational pointer to one explicit milestone contract. Milestone-local files own acceptance and evidence.

## Current contract

- Active milestone: M12 - Route-to-target solving and path requirements.
- Contract: [`docs/milestones/M12/GOAL.md`](milestones/M12/GOAL.md).
- Status: In progress.
- Semantic review: `PASS` on 2026-07-15 in [`SEMANTIC_REVIEW.md`](milestones/M12/SEMANTIC_REVIEW.md).
- Native Codex goal: Active as task goal `019f66ba-d396-7192-a445-a7277e84edf5` with the exact amended done condition.
- Integration head: `fa8c543f648e085403f7448ab5e89f9b6e6c4fb6`.
- Pull request: Not set.

The user explicitly approved and activated M12 on 2026-07-15. M11 remains the latest completed
product milestone and merged through [PR #20](https://github.com/nmpraveen/renpy-story-mapper/pull/20)
at `26502e88bd81b7a1934a6957724fd62f7ba5fbec`. Broad M12 implementation requires the single
semantic-review gate recorded `PASS`; broad implementation is active.

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
