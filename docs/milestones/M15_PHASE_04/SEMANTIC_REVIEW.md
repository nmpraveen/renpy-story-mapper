# M15.1 Phase 04 semantic review

Date: 2026-07-26

Decision: REVISE

## Why the earlier PASS is no longer active

The prior review correctly evaluated the prior contract, but that contract required a
production-grade workflow: 22 acceptance criteria, extreme-scale fixtures, exhaustive recovery and
cursor matrices, several protocol/schema freezes, per-track exact-head reviews, repeated CI, and a
large private acceptance proof. The user has now explicitly rejected that product standard.

The user-authoritative outcome is a quick, crude script-to-story conversion for personal checking.
Therefore the earlier semantic `PASS` is historical only and cannot authorize more work under its
old scope. Existing useful code remains valid; remaining old acceptance work does not.

## Revised contract review checklist

One fresh lightweight independent reviewer must answer only these questions:

1. Does `GOAL.md` make the quick rough full-game story map the observable done condition?
2. Can the current `2995d99` implementation be completed by connecting existing mapping,
   section/overview, publication, workflow API, and browser seams instead of creating another
   architecture?
3. Are Python-owned choices, routes, state changes, rejoins, endings, Path, and Detail/Evidence
   preserved while AI owns prose only?
4. Is real MsDenvers output tested early and judged for usefulness rather than production-grade
   precision?
5. Are private input, read-only source, non-execution, and explicit provider consent boundaries
   preserved?
6. Are worker count, models, reviews, tests, CI, and Release gates quota-aware and consistent with
   the user's new instructions?
7. Are superseded extreme-scale, exhaustive-recovery, `NEW`-diff, per-track-review, and repeated
   full-gate requirements clearly nonblocking?

If all seven answers are yes with no concrete current-game blocker, record a new exact-head `PASS`
and resume. If a required behavior remains ambiguous, pause and ask the user. Do not solve
ambiguity by adding infrastructure.

## Current implementation boundary

- Product checkpoint: `2995d99` on `codex/m15-phase04-full-game`.
- Preserve useful existing Phase 04 code and repository-wide CI acceleration.
- No product edit, worker dispatch, private input access, provider call, or CI run is part of this
  documentation reset.
- Until the fresh review passes, permit only read-only inspection and contract correction.

REVISE
