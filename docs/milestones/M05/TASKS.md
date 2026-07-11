# M05 Task Register

Milestone branch: `milestone/m05-ai-story-explorer`

Milestone base: `0ae86f79c4ed18b4c8a33ee4a98b1a097521e4d5`

Runtime authority: Windows with CPython 3.12

## Work packages

| Task ID | Title | Responsibility | Assigned branch/worktree | Owned files or subsystem | Status | Final commit |
| --- | --- | --- | --- | --- | --- | --- |
| `019f5116-c600-71a3-b933-de9a2e0f92bd` | M05 - Story Organization Model | Schema v4, migrations, organization records, quotient event/arc graph, corrections, and caching | `codex/m05-story-model`; `C:\Users\prave\.codex\worktrees\m05-story-model\Renpy` | Storage/story-domain modules and tests; no provider or UI code | Delivered; first candidate returned for cache, coverage/order, review-before-apply, pinned-rerun, evidence, and corruption-safety gaps; corrected, independently verified, and integrated | Worker `f2ea8c4` + `9345924`; integrated `c3e34a4` + `9bd2f7c` |
| `019f5117-6cfe-75f0-a934-887c14245b0a` | M05 - Secure Codex Organizer | Codex CLI discovery, ChatGPT/LM Studio modes, chunking, schemas, validation, cancellation, consent boundary, and sanitized errors | `codex/m05-codex-organizer`; `C:\Users\prave\.codex\worktrees\m05-codex-organizer\Renpy` | New provider/organization package and mocked process tests; no UI or storage migrations | Delivered; first candidate returned for lifecycle, privacy, ordering, cache-profile, input-minimization, and chunk-boundary gaps; corrected, independently verified, and integrated | Worker `c81f158` + `04d1e61`; integrated `c937a6b` + `ac6f38e` |
| Pending | M05 - Deterministic layout and fixtures | Layered layout, branch lanes, semantic styles, representative story and evaluation fixtures | `codex/m05-layout-and-fixtures`; worktree pending | Canvas/layout modules plus new fixtures/tests; no shell, provider, or storage edits | Planned after shared contracts | Pending |
| Pending | M05 - Arc-first Story Explorer UI | Welcome screen, three-pane workspace, review flow, inspector, corrections, adaptive theme, accessibility, screenshots, and UI tests | `codex/m05-story-explorer-ui`; worktree pending | UI package after shared contracts; no provider or storage implementation | Planned after model/provider/layout integration | Pending |
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
