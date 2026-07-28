# M15.1 Phase 05 semantic review

Review target: revised `MASTER_PLAN.md`, `GOAL.md`, `TASKS.md`, and `PROJECT_STATE.md`.

Status: REVISE (Codex CLI summary-provider delta awaiting review)

## Required decision

- Does the contract correct the demonstrated incomplete-parser blocker before more grouping/UI
  work?
- Is trusted Ren'Py use confined to a disposable copy while supplied originals remain unchanged?
- Is the first proof small enough: one real omitted slice, one focused correction, and one local
  four-grade audit?
- Are Ren'Py, Python, and AI responsibilities clear without adding a platform layer?
- Does broader regeneration remain gated on the real slice earning `PASS`?
- Are any P0, P1, or P2 scope, correctness, privacy, or safety problems present?

## Current evidence

- The old 24 groups exactly cover the 425-section projection, but later-game source files contain
  many parsed labels with empty bodies. Therefore the former 425/425 claim is not whole-game proof.
- The user explicitly approved trusted Ren'Py execution and asked to try the smallest useful real
  slice before deciding how much input Ren'Py needs.
- The existing reader and loopback local-model transport are reusable; no new database, workflow,
  API, or UI family is proposed.

## Review result

- Exact target: `17f8400b089f7bf7cb3004058d14a961720b998c`.
- Reviewer: `/root/phase05_extraction_semantic_review`, explicit `gpt-5.6-sol` High; fast mode
  unavailable/unverified.
- Verdict: `PASS` (`P0=0`, `P1=0`, `P2=0`).
- The contract fixes extraction before grouping, confines Ren'Py-created files to a disposable
  copy, keeps Python/AI authority bounded, gates regeneration on one real omitted slice, reuses
  existing seams, and maps all five acceptance criteria to lean evidence.

REVISE
