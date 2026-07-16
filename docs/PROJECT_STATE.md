# Ren'Py Story Mapper project state

Updated: 2026-07-15

`docs/MASTER_PLAN.md` owns product scope. This file owns the operational pointer to one explicit milestone contract. Milestone-local files own acceptance and evidence.

## Current contract

- Active milestone: M12 - Route-to-target solving and path requirements.
- Contract: [`docs/milestones/M12/GOAL.md`](milestones/M12/GOAL.md).
- Status: PR ready.
- Verification context: all four changes requested on PR #22 are resolved and revalidated.
- Semantic review: `PASS` on 2026-07-15 in [`SEMANTIC_REVIEW.md`](milestones/M12/SEMANTIC_REVIEW.md).
- Native Codex goal: Task goal `019f66ba-d396-7192-a445-a7277e84edf5` completed at the prior PR-ready state; no replacement goal was created because the user required a targeted continuation rather than an M12 restart.
- Changes-requested base: `a02151ebc45d2d05efc6d582a8757fbca87aa6d5`.
- Validated product head: `40c10fd9bb31e9303efeb302dacd081e1007911c`.
- Pull request: [PR #22](https://github.com/nmpraveen/renpy-story-mapper/pull/22), open, unmerged, and ready for final user review after the correction push.

The user explicitly approved and activated M12 on 2026-07-15. M11 remains the latest completed
product milestone and merged through [PR #20](https://github.com/nmpraveen/renpy-story-mapper/pull/20)
at `26502e88bd81b7a1934a6957724fd62f7ba5fbec`. M12 passed its single early semantic gate,
implementation, Fast/Focused/Release, scale/browser/private acceptance, and both final reviews at
the prior head. The user then reproduced four merge blockers in constraint intersection, call-frame
completion, prefix accounting, and loop acceleration. Those bounded corrections now pass focused,
Release, browser, persistence/fault, scale, grind, private acceptance, and final review. The final
review's intermediate-loop phase finding was fixed in `40c10fd` and the exact re-review returned
`PASS`.

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
