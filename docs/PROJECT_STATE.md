# Ren'Py Story Mapper project state

Updated: 2026-07-16

`docs/MASTER_PLAN.md` owns product scope. This file owns the operational pointer to one explicit milestone contract. Milestone-local files own acceptance and evidence.

## Current contract

- Active milestone: M13 - Optional AI narrative layer.
- Contract: [`docs/milestones/M13/GOAL.md`](milestones/M13/GOAL.md).
- Baseline: merged `main` at `f67df8a7cb805bf4adf8590585bae700d2f3117f`.
- Integration branch: `codex/m13-narrative-layer`.
- Status: Verification.
- Semantic review: [`PASS`](milestones/M13/SEMANTIC_REVIEW.md) on 2026-07-16.
- Native Codex goal: active thread goal `019f6a76-1675-7ad3-bcbc-8741693751a3`, matching the exact
  M13 done condition.
- Pull request: Not created; explicit user approval is required before creation or merge.

The user approved and activated M13 on 2026-07-16 with binding amendments for bounded internal
summary segments, logical-job/transport-batch separation, a lazy claim DAG, context-aware
contradictions, claim-level salvage, one required cloud adapter, simple manifest consent,
route-aware hierarchy, release-priority order, full provider-free private-scale simulation,
bounded live acceptance, and privacy-safe storage. The single early semantic gate passed; work is
proceeding in the contract's release-critical order.

The integrated product head is `859328e1cbe8933809bd49001d681d1f7f6701d4`. The full Windows
release suite, complete provider-free private-corpus simulation, and real Chrome acceptance at
100%/200% pass. Exact bounded live-provider acceptance remains gated by the prepared consent
manifest and has made zero submissions. A separately configured independent review and the native
infographic also remain before `PR ready`; no pull request has been created.

M12 is complete and merged through [PR #22](https://github.com/nmpraveen/renpy-story-mapper/pull/22)
with normal merge commit `f67df8a7cb805bf4adf8590585bae700d2f3117f` on 2026-07-16. Its
implementation branch was deleted locally and remotely. No further M12 implementation or review
work is authorized unless a critical regression is demonstrated.

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
