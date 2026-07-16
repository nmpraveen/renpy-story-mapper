# Ren'Py Story Mapper project state

Updated: 2026-07-16

`docs/MASTER_PLAN.md` owns product scope. This file owns the operational pointer to one explicit milestone contract. Milestone-local files own acceptance and evidence.

## Current contract

- Active milestone: M13 - Optional AI narrative layer.
- Contract: [`docs/milestones/M13/GOAL.md`](milestones/M13/GOAL.md).
- Baseline: merged `main` at `f67df8a7cb805bf4adf8590585bae700d2f3117f`.
- Integration branch: `codex/m13-narrative-layer`.
- Status: Blocked in verification on live-provider acceptance, consent-manifest identity, and the
  missing independent final-head `PASS`.
- Semantic review: [`PASS`](milestones/M13/SEMANTIC_REVIEW.md) on 2026-07-16.
- Native Codex goal: blocked task/goal `019f6ce8-55e7-76a2-9f64-202d00ebb9a5`; not complete.
- Pull request: Not created; explicit user approval is required before creation or merge.

The user approved and activated M13 on 2026-07-16 with binding amendments for bounded internal
summary segments, logical-job/transport-batch separation, a lazy claim DAG, context-aware
contradictions, claim-level salvage, one required cloud adapter, simple manifest consent,
route-aware hierarchy, release-priority order, full provider-free private-scale simulation,
bounded live acceptance, and privacy-safe storage. The single early semantic gate passed; work is
proceeding in the contract's release-critical order.

The frozen runtime correction head is `e0fd3bf3dba34a2d936028f3df8773e69d9fc1c8`.
Final-head focused tests passed 70 tests, and Release passed 966 tests with 7 hardware-sensitive
tests deselected plus Ruff, strict mypy, dependency, JavaScript, whitespace, isolated package
build/install/import, asset, and notice checks. Provider-free acceptance passed all 1,812 private
scenes, and real Chrome acceptance passed at 100%/200% with zero remote requests and zero-call
simulator replay.

The one independently configured corrective rereview used `gpt-5.6-sol`, High reasoning, fast
mode disabled, ephemeral/read-only execution, and range `04082c0..9889035`; it returned `FAIL`
with two P1 findings. The single permitted corrective cycle produced `e0fd3bf` and focused/Release/
private/browser checks pass, but no second independent verdict was authorized. The fresh live
manifest was explicitly approved, including external transmission risk. Its one execution failed:
74 jobs, 222 transient-failure attempts, 24 provider calls, zero recorded tokens, no artifacts,
and no replay. It also demonstrated that the previewed consent ID `m13_consent_3bb95e...` changed
to unpreviewed granted ID `m13_consent_d2b91d...` in persisted provider requests. Per the bounded
severity policy, no retry or second correction loop was started. After the same terminal condition
persisted for three consecutive goal turns, the native goal was marked blocked. The native
infographic is complete, and no pull request has been created.

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
