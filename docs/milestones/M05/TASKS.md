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
| `019f52eb-e558-7971-b511-0ddd020401b5` | Create branching fixture | Synthetic multi-route Ren'Py fixture with gates, effects, calls, loop, merge, four endings, and one unresolved dynamic jump | `codex/m05-complex-branching-fixture`; `C:\Users\prave\.codex\worktrees\ccd4\Renpy` | `tests/fixtures/m05/complex_branching` only | Delivered, independently verified, integrated, and locked by an executable pipeline contract | Worker `109dfe0`; integrated `f7ad6f3` + `9d714b5` |
| `019f540f-eb55-7bd3-8293-02ac26f5f880` | M05 - Independent final review | Adversarial acceptance review, new review tests, full Windows suite, and P0-P3 findings | `codex/m05-independent-review`; `C:\Users\prave\.codex\worktrees\bda7\Renpy` | New review tests/fixtures and evidence only; production edits excluded | Production blockers accepted after re-review; acceptance documentation remained with orchestrator | Review `df24a9e` + `4575cb4`; integrated `8931d4f` + `7ab7041` |

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
- 2026-07-11: Integrated the synthetic complex branching fixture and executable manifest contract,
  then fixed persisted quotient connectivity across ungrouped technical chains. Stabilized the
  ChatGPT-only interface at GPT-5.6 Luna, High reasoning, and disabled fast mode.
- 2026-07-11: Real Luna structured-output preflight exposed unsupported `uniqueItems` keywords and
  a missing explicit type on the schema discriminator. Corrected all three packaged schemas while
  retaining deterministic duplicate validation; a real no-story schema probe then passed.
- 2026-07-11: The authorized synthetic live run completed 12 provider calls in 569.801 seconds but
  failed safely before draft creation because Stage-2 character permissions were request-wide
  rather than exact-member scoped. The deterministic authority remained unchanged.
- 2026-07-11: Exact-member character filtering corrected that cross-validator mismatch. A cached
  live retry used 11 cache hits and one Luna call in 92.441 seconds, producing a validated pending
  draft with 2 arcs, 22 AI events, and 71 evidence-linked claims. Review/apply added two selected-
  scope deterministic fallbacks for 24 displayed events, derived 57 event edges, retained 114
  attached facts, and preserved 26 requirements, 88 effects, and one unresolved record.
- 2026-07-11: Rename, pin, approval, and reopen persistence passed. An unchanged rerun used all 12
  cache entries with zero provider calls. The native Windows harness passed on the live organized
  project with 55 rendered items, exact evidence, isolated INI settings, and no provider call on
  open.
- 2026-07-11: Started the single final independent review task
  `019f540f-eb55-7bd3-8293-02ac26f5f880` from integration commit `9059acd` in a dedicated Windows
  worktree with GPT-5.6 Sol, High reasoning, and fast mode disabled. Production edits are excluded.
- 2026-07-11: Independent review returned three production P2 findings: fail-open Luna/profile
  selection, incomplete cache identity, and cross-target claim evidence. The orchestrator fixed all
  three, verified 347 tests plus Ruff, strict mypy, and pip integrity, and pushed `fc239ce`.
- 2026-07-11: The same review task strengthened its four adversarial tests and accepted every
  production fix. Its only remaining P2 is acceptance evidence: the separately consented real
  script smoke, final report, and infographic.
- 2026-07-11: A fresh synthetic Luna/High run against the corrected cache identity made 12 provider
  calls and safely exposed duplicate reconciled outcome values at final draft validation. Stable
  de-duplication and a regression test were committed as `e8be732`.
- 2026-07-11: The corrected retry used all 12 cache entries, launched no provider, completed in
  174 ms, and produced a pending 33-event, four-arc, 77-claim draft while preserving deterministic
  authority hash `337e5158a1d62d22b7ee76f68b2704b2077343f75e9a14e4781f61aad08ed618`.
  Sanitized metrics, storage growth, and seven native UI screenshots are retained in this folder.
- 2026-07-11: After fresh user consent, the real `script small new.rpy` source was fingerprinted,
  copied to temporary storage, and organized through four Luna/High calls in 89.302 seconds. The
  proposed one arc, four events, and 14 claims passed validation; deterministic authority stayed
  byte-logically identical.
- 2026-07-11: The real-script review/apply retained six technical beats as explicit fallback events
  and produced nine locally derived event edges. A rerun used four cache hits, zero provider calls,
  and 54 ms. The original source SHA-256, size, and LastWriteTimeUtc were identical afterward.
- 2026-07-11: The normal Windows Qt harness captured readable technical-before, accepted-after,
  event, evidence, and AI-review views with no provider call on open. The headless offscreen plugin
  reported zero fonts, so it was correctly rejected as release evidence.
