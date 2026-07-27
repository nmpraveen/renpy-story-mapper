# **QUICK, CRUDE SCRIPT TO STORY CHECKER — NOT A PRODUCTION-GRADE SYSTEM**

## M15.1 Phase 04 — finish the full-game story map

Status: In progress

Scope authority: the user's 2026-07-26 simplicity reset, `docs/MASTER_PLAN.md`, and
`docs/MILESTONE_PLANNING_RULES.md`.

The earlier production-grade Phase 04 contract is superseded. Its useful implementation stays in
place, but its 22 acceptance criteria, extreme-scale targets, exhaustive recovery/tamper matrices,
per-track exact-head reviews, and repeated full gates are no longer product requirements.

## Ultimate rule

**LOAD REN'PY FILES, QUICKLY SHOW THE ROUGH WHOLE STORY, AND MAKE THE IMPORTANT CHOICES, ROUTES,
STATE CHANGES, AND REJOINS EASY TO SEE. IF WORK DOES NOT DIRECTLY HELP THAT RESULT OR REMOVE A
DEMONSTRATED BLOCKER, DO NOT BUILD IT. PAUSE AND ASK.**

## Done condition

Phase 04 is done when the supported local website can take the current MsDenvers project through
one understandable workflow and produce a useful rough full-game map:

- a chronological whole-story overview;
- readable story sections and short AI summaries;
- visible local choices and their outcomes;
- persistent alternative routes, important state changes, and known rejoins/endings;
- working Path and Detail/Evidence navigation for sampled visible items; and
- honest structural placeholders when an AI summary is unavailable.

The user must be able to inspect the real result and say it is useful for quick personal story
checking. Perfect prose, perfect AI reproducibility, publication-level accuracy, exhaustive edge
case handling, and production-grade service guarantees are not required. The final Phase 04 PR
must be ready, open, and unmerged.

## Current safe checkpoint

- Integration branch: `codex/m15-phase04-full-game`.
- Current local head before this scope reset: `2995d99`.
- Draft PR: #30, open and unmerged.
- Useful foundations already exist: occurrence-aware planning/chunking, durable workflow storage,
  cloud mapping execution, semantic event/section components, scalable reader/browser components,
  repository-wide sharded CI, and durable section-job scheduling.
- The last implementation checkpoint reported 119 focused tests passing. This scope-reset change
  runs documentation checks only and does not repeat product tests.
- The prior coordinator task `019f7fe2-eeaa-7622-b3eb-f53d5bd5f749` created the historical goal,
  but both the new Orchestra and the prior task's last recorded goal check returned no accessible
  goal. The user authorized replacement with the lean-contract goal on Orchestra task
  `019fa176-8277-7920-8558-b816cf168a9f`.
- Fresh lightweight semantic review passed at exact contract head `2bcdd02`. The two bounded
  vertical-path workers are integrated through `2776b99`; the focused integrated gate passed 123
  tests plus Ruff, strict mypy over the six changed source files, JavaScript syntax, and whitespace.
- Lifecycle is `Integration`. The next gate is the supported-website zero-submit MsDenvers preview;
  no private story text may be transmitted until the user approves that exact preview.

## Must work in Phase 04

1. Finish the shortest backend path from an approved prepared run to accepted chunk summaries,
   simple section/overview prose, and one published readable generation.
2. Expose the existing prepare/start/status/cancel/resume behavior through the website and connect
   it to the existing story reader. Keep controls unavailable when the backend does not advertise
   them; do not invent another protocol family.
3. Show progress plainly, then show the rough whole story with choices, routes, state changes,
   rejoins, Path, and Detail/Evidence.
4. Run the current MsDenvers project early through that supported workflow after a zero-submit
   preview and exact user consent for private AI transmission.
5. Fix only blockers that make the real output unusable or violate read-only/privacy boundaries.

## Lean execution gates

### Gate 0 — scope reset and lightweight semantic review

- Treat this file as the only active Phase 04 acceptance contract.
- Use one short independent review to confirm the plan can reuse the current implementation and
  does not accidentally revive the superseded production requirements.
- On uncertainty, record `REVISE`, pause, and ask the user. Do not start another architecture pass.

### Gate 1 — shortest end-to-end product path

Use no more than two concurrent user-visible worker tasks:

- **Backend/API worker:** finish only the missing accepted-summary → simple section/overview →
  generation publication path and the existing workflow command/status web composition.
- **Website worker:** connect the existing controls and reader to that minimal frozen API and make
  the chronological map readable at normal desktop and 200% zoom.

Reuse existing code and contracts wherever they are good enough. Do not introduce a schema,
scheduler, protocol version, migration, cache layer, diff system, or recovery subsystem unless a
failing current end-to-end case proves it is necessary and the user approves it.

### Gate 2 — real MsDenvers check

- Prepare with zero provider construction/calls and show the exact model, private material, chunk
  count, and maximum calls.
- Obtain exact consent before transmitting private story text.
- Run the supported website workflow and inspect Day 1 plus representative later local choice,
  persistent route, rejoin, state-dependent scene, and ending.
- Judge usefulness, not perfect wording. Clearly marked missing summaries are acceptable if the
  whole deterministic route structure remains visible and the overall story is still useful.
- Show the user the result and pause for feedback before polishing or broadening anything.

### Gate 3 — blocker-only correction

Make one bounded correction pass for problems the real check actually exposed. A second design
loop, new architecture layer, or broad hardening effort requires the user's approval.

### Gate 4 — lean final verification and PR readiness

- Run the affected/focused Story Map V2 tests and direct static checks.
- Run one independent integrated review with no unresolved P0-P2 on the lean contract.
- Obtain user approval of the final normal/200% screenshots; narrow-layout checks are required only
  if this phase changes narrow-layout behavior.
- Push the intended PR candidate once, use the repository-wide timing-balanced sharded CI, and run
  one final Windows Release/package gate on the intended final head.
- Record evidence and leave PR #30 open and unmerged.

## Acceptance criteria

1. A user can prepare the current game through the website without creating a provider or making an
   AI call, and the preview plainly discloses private transmission and finite call limits.
2. After exact consent, the workflow can process chunks, keep completed work, and resume ordinary
   pending work after reopen without resubmitting completed chunks.
3. The final deterministic structure contains the reachable story placements, choices, arms,
   persistent routes, known state changes, rejoins, and endings supplied by existing Python
   authority. AI writes prose only and cannot replace those mechanics.
4. The website presents a readable chronological whole-story overview and sections with nested
   branches/routes rather than a generic spread-out graph.
5. Sampled Day 1 content remains consistent with the accepted Phase 03 result, and representative
   later choice, route, rejoin, state-dependent scene, and ending are understandable.
6. Every sampled visible item can open the existing Path and Detail/Evidence views. Unavailable AI
   prose is labeled honestly without hiding the structural route.
7. Source/archive inputs remain read-only, no game/Ren'Py/creator code executes, opening or reading
   makes no implicit provider call, and private source/prompts/responses/screenshots stay outside
   Git.
8. The user accepts the real output as useful for quick checking; one final integrated review,
   focused checks, sharded CI, and one Release/package gate pass; PR #30 is ready and unmerged.

## Evidence required

| Criterion | Minimum evidence |
|---|---|
| 1-2 | Zero-submit preview, consent identity, concise terminal job counts, reopen/resume result |
| 3-6 | Sanitized real-game counts plus a small sample of Day 1, local choice, persistent route, rejoin, state-dependent scene, ending, Path, and Detail/Evidence |
| 7 | Before/after protected-input fingerprints and a concise privacy/non-execution statement |
| 8 | User screenshot/output approval, one final review verdict, focused commands/results, sharded CI run, Release/package result, and PR state |

## Explicitly deferred or removed from acceptance

- Production-grade multi-process guarantees and exhaustive crash timing matrices.
- Extreme synthetic targets such as 5,000 events, 20,000 arms, depth-eight branches, fixed memory
  budgets, or exhaustive cursor/tamper tests. Existing passing work may remain; do not expand it.
- Perfect cache identity proofs, exact prose replay, deterministic AI wording, formal coverage
  proofs, and publication-grade accuracy.
- Cross-version `NEW` badges, advanced stale-generation diffing, exhaustive search/paging scale,
  and full legacy retirement unless already working at no material cost. Phase 05 may reconsider
  product cleanup after the core result is accepted.
- Per-worker exact-head reviewers, continuous orchestration monitoring, repeated hosted CI, and a
  full Release after every correction.
- New Stage H/E, M13 scheduler reuse, M14 tracing, installer work, hosted deployment, game editing,
  or creator-code execution.

Existing implemented hardening does not need to be deleted unless it blocks the simple workflow.
It simply is not a reason to add more hardening.

## Agent and orchestration rules

- One user-visible Orchestra task owns scope, decisions, worker dispatch, integration, and
  checkpoint reporting.
- For this resumption, every implementation worker and reviewer must be created with
  `gpt-5.6-sol` and Medium reasoning. The current user-visible task API has no fast-mode selector;
  the user explicitly authorized dispatch with fast mode recorded as unavailable/unverified, never
  claimed disabled.
- The user intends to use an Ultra-reasoning chat for planning/Orchestra work. Repository prose does
  not set that model; the new chat must rely on the user's actual selection.
- Keep at most two implementation workers active at once. Use one lightweight semantic reviewer
  before work and one integrated reviewer near the end.
- The Orchestra checks milestone completions and blockers, not continuous commentary or healthy CI.
- When necessity, scope, or value is uncertain, pause the goal and ask the user.

## Handoff rules

Each worker returns its exact base/head, changed files, focused checks/results, assumptions, known
defects, and one sentence explaining how the work directly improves the script-to-story result.
The Orchestra integrates only the lean required path, updates this contract with factual evidence,
and stops at user-decision gates. Do not merge PR #30 without separate explicit user approval.
