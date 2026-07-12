# M05 Task Register

Milestone branch: `milestone/m05-ai-story-explorer`

Milestone base: `0ae86f79c4ed18b4c8a33ee4a98b1a097521e4d5`

Runtime authority: Windows with CPython 3.12

## Work packages

| Task ID | Title | Responsibility | Assigned branch/worktree | Owned files or subsystem | Status | Final commit |
| --- | --- | --- | --- | --- | --- | --- |
| `019f5116-c600-71a3-b933-de9a2e0f92bd` | M05 - Story Organization Model | Schema v4, migrations, organization records, quotient event/arc graph, corrections, and caching | `codex/m05-story-model`; `C:\Users\prave\.codex\worktrees\m05-story-model\Renpy` | Storage/story-domain modules and tests; no provider or UI code | Delivered; first candidate returned for cache, coverage/order, review-before-apply, pinned-rerun, evidence, and corruption-safety gaps; corrected, independently verified, and integrated | Worker `f2ea8c4` + `9345924`; integrated `c3e34a4` + `9bd2f7c` |
| `019f5117-6cfe-75f0-a934-887c14245b0a` | M05 - Secure Codex Organizer | Codex CLI discovery, ChatGPT/LM Studio modes, chunking, schemas, validation, cancellation, consent boundary, and sanitized errors | `codex/m05-codex-organizer`; `C:\Users\prave\.codex\worktrees\m05-codex-organizer\Renpy` | New provider/organization package and mocked process tests; no UI or storage migrations | Delivered; first candidate returned for lifecycle, privacy, ordering, cache-profile, input-minimization, and chunk-boundary gaps; corrected, independently verified, and integrated | Worker `c81f158` + `04d1e61`; integrated `c937a6b` + `ac6f38e` |
| `019f5142-640e-7350-b2bc-69acb7f5fa2a` | M05 - Deterministic Layout and Fixtures | Layered layout, branch lanes, semantic styles, representative story and evaluation fixtures | `codex/m05-layout-and-fixtures`; `C:\Users\prave\.codex\worktrees\m05-layout-and-fixtures\Renpy` | Canvas/layout modules plus new fixtures/tests; no shell, provider, or storage edits | Delivered, diff-inspected, independently verified, and integrated | Worker `c9c15b1`; integrated `9b1e98d` |
| `019f5149-c76d-7193-a165-a7697ebb86eb` | M05 - Arc-first Story Explorer UI | Welcome screen, three-pane workspace, organization controller, review flow, inspector, corrections, adaptive theme, accessibility, screenshot harness, and UI tests | `codex/m05-story-explorer-ui`; `C:\Users\prave\.codex\worktrees\m05-story-explorer-ui\Renpy` | UI package and synthetic UI tests/harness after accepted model/provider/layout contracts; no provider or storage implementation | Delivered and integrated; adversarial UI correction is active on the milestone branch | Worker `6b8bbb9`; integrated `011f585` |
| `019f5116-c600-71a3-b933-de9a2e0f92bd` (corrective turn) | M05 - Scoped Organization Integrity | Partial-scope draft validation/apply semantics and complete deterministic edge retrieval across presentation pages | `codex/m05-scoped-organization`; `C:\Users\prave\.codex\worktrees\m05-scoped-organization\Renpy` | Story-organization domain plus a narrow read-only presentation API and focused tests; no UI/provider/layout edits | Delivered, independently verified, and integrated | Worker `6bbf12e`; integrated through `65644e5` |
| `019f5117-6cfe-75f0-a934-887c14245b0a` (corrective turn) | M05 - LM Studio Model Preflight and Cancellation Margin | Resolve the local model before cache lookup and tighten Windows process shutdown under the two-second end-to-end gate | `codex/m05-provider-preflight`; `C:\Users\prave\.codex\worktrees\m05-provider-preflight\Renpy` | Provider contracts/process boundary and focused mocked Windows tests; no UI/storage/layout edits | Delivered, independently verified, and integrated | Worker `d2ef42a`; integrated `fd688ff` |
| `019f51f6-2614-7621-9954-6ec9f3c840b2` | M05 - Real LM Studio Structured Output | Historical LM Studio structured-output correction task | `codex/m05-runtime-structured-output`; `C:\Users\prave\.codex\worktrees\1602\Renpy` | Provider/contracts only | Deferred by the approved ChatGPT-only M05 revision; do not retry during M05 | Deferred |
| Pending | M05 - Independent final review | Adversarial acceptance review, new review tests, full Windows suite, and P0-P3 findings | `codex/m05-independent-review`; worktree pending | New review tests/fixtures and evidence only; production edits excluded | Planned after full integration | Pending |

The orchestrator owns the cross-package contracts, worker monitoring, diff inspection, integration,
conflict resolution, canonical archive handling, complete Windows acceptance, final documentation,
native infographic generation, and the single unmerged M05 PR.

## Required worker brief and return contract

Every worker receives a bounded objective, exact base commit, assigned branch/worktree, owned files
or subsystem, deliverables, required tests, exclusions, and integration order. Every worker must
return its task ID, status, branch and worktree, final commit, changed files, delivered behavior or
findings, exact commands and results, performance/security evidence where relevant, known
limitations, risks, unresolved questions, integration instructions, and confirmation that it stayed
inside scope.

## Integration order

1. Integrate the story-model and provider contracts.
2. Start and integrate deterministic layout and evaluation fixtures.
3. Start and integrate the Story Explorer UI against the accepted shared contracts.
4. Run the independent review only after the integrated implementation and orchestrator acceptance
   suite are ready.
5. Return defective work to its responsible task; a worker's completion claim is never acceptance.

## Activity log

- 2026-07-11: User explicitly approved and started M05.
- 2026-07-11: Synchronized clean `main` at merged M04 PR #6 commit `0ae86f7`.
- 2026-07-11: Created the single M05 self-goal and `milestone/m05-ai-story-explorer`.
- 2026-07-11: Recorded the approved detailed M05 specification in `docs/MASTER_PLAN.md`.
- 2026-07-11: Verified the clean worker baseline on Windows CPython 3.12: 133 pytest tests passed;
  Ruff, strict mypy, and `pip check` passed.
- 2026-07-11: Started the story-model and secure-organizer user-visible tasks in separate explicit
  Git worktrees from documentation commit `44ecfca`.
- 2026-07-11: Local provider preflight found `codex-cli 0.144.0`; LM Studio was not listening on
  localhost port 1234, so canonical AI acceptance remains gated on the later user-started model.
- 2026-07-11: Returned the secure-organizer candidate for eight concrete review gaps. The corrected
  branch passed 43 focused and 176 full tests plus Ruff, strict mypy, and `pip check`; the
  orchestrator independently reran the same 43 focused tests before integration.
- 2026-07-11: Returned the story-model candidate for ten concrete contract and safety gaps. The
  corrected branch passed 11 focused and 144 full tests; after integration with the organizer,
  the orchestrator verified 187 pytest tests, Ruff, strict mypy across 31 source files, and
  `pip check` on Windows CPython 3.12.
- 2026-07-11: Started the deterministic-layout and evaluation-fixtures task from integrated commit
  `cc86cfa` in its own explicit branch and Git worktree.
- 2026-07-11: Integrated the deterministic layout after inspecting its 838-line candidate diff and
  independently verifying 9 focused and 196 full tests, Ruff, strict mypy across 32 source files,
  `pip check`, and `git diff --check`. The representative layout hash is
  `369cf3be135d2b7a0aa45c8b4baaee9bf0b789123ab8e87c187e25898896d256`; the worker measured the
  240-item fixture at 1.617 ms median and 1.809 ms p95 across 200 runs.
- 2026-07-11: Started the arc-first Story Explorer UI and organization-workflow task from accepted
  integration commit `bcb5019` in its own explicit branch and Git worktree.
- 2026-07-11: Pre-integration UI review proved that global draft validation would turn every
  out-of-scope required beat into a one-beat fallback and that page-bounded presentation queries
  could omit authoritative cross-page transitions. Reactivated the Story Organization Model task
  in a new non-overlapping worktree for scoped atomic apply and complete edge-retrieval contracts;
  the UI workflow now fails closed until those contracts are integrated.
- 2026-07-11: Reactivated the Secure Codex Organizer task in a second non-overlapping corrective
  worktree after review proved that a default LM Studio run could not identify its model before the
  first cache lookup and that the existing process-stop budget left effectively no margin inside
  the two-second end-to-end cancellation acceptance gate.
- 2026-07-11: Integrated the Story Explorer candidate, then ran an independent adversarial audit.
  The audit found full-game scope, canonical-scale input, Stage-2 prompt bounding, scoped review,
  render-cap, filter/correction, contextual-error, settings-isolation, and accessibility defects.
  Bounded workflow-scale and Story Explorer corrections were assigned on non-overlapping files.
- 2026-07-11: Started LM Studio locally without story input and loaded instance
  `m05-gpt-oss-20b` with a 32,768-token context. Native preflight passed, but a real synthetic-only
  organizer run returned schema-invalid output twice. Created user-visible corrective task
  `019f51f6-2614-7621-9954-6ec9f3c840b2` from provider commit `d2ef42a`; task control stopped it with
  the current usage-limit system error, so its intact branch/worktree is awaiting an exact retry.
- 2026-07-11: Revised the remaining M05 plan by user direction: the only exposed AI path is
  consent-gated GPT-5.6 Luna with High reasoning and fast mode disabled. The complex branching
  fixture is the primary live-AI acceptance source; `script small new.rpy` is a secondary
  separately consented smoke source. LM Studio and full canonical-game AI organization are
  deferred and the paused LM Studio task must not be retried during M05.
