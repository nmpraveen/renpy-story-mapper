# M15.1 Phase 04 progress report

Status: Blocked — the exact approved Gate 2 run ended indeterminate without a map

Current product checkpoint: `4a85a79` on `codex/m15-phase04-full-game`

Pull request: #30, draft, open and unmerged

## Outcome so far

The branch contains substantial useful implementation: full-game occurrence planning and chunking,
durable workflow storage, cloud mapping execution, semantic events/sections, scalable reader and
browser work, repository-wide sharded CI, product workflow composition, and durable section jobs.
The last implementation checkpoint reported 119 focused tests passing.

The work stopped at a clean code checkpoint after the user identified the actual bottleneck:
Phase 04 had become a production-grade platform project rather than a quick script-to-story tool.
No current product code is being discarded, but the remaining old acceptance work is superseded.

## Scope-reset result

- The active done condition is now one useful real MsDenvers story map, not exhaustive production
  guarantees.
- The old 22-criterion contract, extreme scale matrix, exhaustive recovery/tamper work, per-track
  reviewers, and repeated full gates are no longer acceptance requirements.
- Future execution uses one Orchestra, at most two workers, one early review, one final integrated
  review, focused tests, sharded CI once at the PR-candidate boundary, and one final Release gate.
- For the next resumption, workers/reviewers use `gpt-5.6-sol` with Medium reasoning.
- A fresh lightweight reviewer answered all seven lean-scope questions YES and recorded `PASS` at
  exact clean head `2bcdd02`; no architecture or production-grade acceptance work is required.

## Resumption record

- The current Orchestra verified branch `codex/m15-phase04-full-game` at contract commit
  `2bcdd02e15d6570a232ee6f70ed8daa21aa05619`.
- The prior coordinator's recorded native goal was inaccessible from both the new Orchestra and the
  prior task's last recorded goal check. The user authorized one replacement lean-contract goal on
  task `019fa176-8277-7920-8558-b816cf168a9f`.
- The task dispatcher exposes model and reasoning selectors but no fast-mode selector. The user
  authorized explicit `gpt-5.6-sol` Medium dispatch with fast mode recorded as
  unavailable/unverified.
- Semantic review task `019fa18a-816a-77b2-99b1-1717ef117a54` independently inspected the full
  authority chain and implementation seams read-only. It found no blocker and confirmed the
  smallest remaining work is backend/API composition plus website control wiring.
- Backend/API task `019fa18f-e895-71d3-ac9e-49e81ef77c7b` and website task
  `019fa18f-f055-7411-ac72-acbddf2b4f8d` started concurrently from exact semantic-gate commit
  `21d80d208f4f505f39e6649df246d88e8688bb82` in separate clean branches/worktrees with disjoint
  Python/backend and static-website ownership.
- Backend worker head `3723da9` integrated as `29f4378`. It composes the existing workflow,
  semantic/derived assemblers, structural fallback, durable repository, atomic generation
  publisher, reader records, frozen HTTP routes, and the web server's existing single executor.
  Its fake-provider handoff passed 141 focused workflow/reader tests and 19 adjacent API tests,
  Ruff, and strict mypy.
- Website worker heads `cdfd37a` and `b4572aa` integrated as `b8bf018` and `2776b99`. The website
  now provides prepare/approval/start/status/cancel/resume, progress, reader refresh, and bounded
  reopen restoration using the existing frozen route family; its focused browser and asset checks
  passed at normal, effective-200%, and narrow layouts.
- The Orchestra's single focused integrated gate passed 123 tests in 44.41 seconds across the
  product workflow, derived semantics, frozen workflow contract, reader, browser, and adjacent web
  API, plus Ruff, strict mypy over all six changed source files, JavaScript syntax, and whitespace.
- No new schema, protocol, scheduler, recovery subsystem, provider call, private input access,
  push, PR mutation, or merge occurred during worker implementation or integration.

## Gate 2 zero-submit checkpoint

- The supported website opened the current 57-source full-game MsDenvers project. Its first load
  demonstrated that Generate was hidden when no reader generation existed. The responsible website
  worker made the single bounded blocker correction at `b5e222e` plus Orchestra-requested
  off-workspace guard `4852337`; these integrated as `b2d3e6a` and `4a85a79`.
- The corrected live website exposes the same existing Generate action in the technical fallback
  workspace. Normal and effective-200 approval views have zero horizontal overflow; the short 200%
  dialog scroll exposes the unchanged approval action.
- Exact zero-submit preview identity is
  `9d449b95c7f241104686318cce7c2595569551603bc4a8b7aa8662ac70a3a2c1` for run
  `workflow:0cfddba52e4a4262bfdb1915dd15a612`: Codex CLI, `gpt-5.6-terra`, High reasoning,
  fast mode off, 425 chunks/jobs, 2,927 maximum cloud calls, zero local calls, and zero cache hits.
- Provider accounting is exactly zero calls, zero input/output tokens, and zero elapsed provider
  time. The browser observed only loopback requests. Private raw story text plus exact mechanics may
  be sent by mapping calls; derived calls may send accepted child summaries and route/rollup
  structure. Raw requests/responses, provider diagnostics, and absolute paths are not durable.
- Protected `.rpy`/`.rpyc`/`.rpa` aggregate SHA-256 remained
  `0a3391b63c5b18e76cfa1bded722a8e5d8a62fbc74e5e1c26eb9dd9179d10762` before and after.
  Sanitized preview evidence and screenshots remain outside Git under
  `output/m15-phase04-gate2-preview-20260727-0009/`.
- The user explicitly replied `Approved proceed` on 2026-07-27. Immediately before activation, a
  fresh durable and website preflight reconfirmed the unchanged preview/run identity, no approval,
  all 425 jobs pending, and zero calls/tokens.
- The Orchestra activated `#approveStoryGeneration` exactly once through the supported website.
  No second click or prepare occurred. The durable ledger then showed the exact approval stored and
  the finite run executing. Early mapping calls returned the sanitized failure `The configured
  mapper is unavailable.` with zero tokens; the workflow continues recording structural fallback
  or indeterminate outcomes rather than inventing AI prose.
- The run reached its durable stopping point without intervention: 425 calls, 0 accepted jobs, 19
  structural fallbacks, 406 indeterminate jobs, 0 input/output tokens, no active or pending jobs,
  no complete/active generation, and `map_revision=0`. Consequently there is no new real map for
  the required representative website inspection or user usefulness decision.
- Local non-provider diagnostics confirm Codex CLI 0.144.0 is installed, logged in through
  ChatGPT, and recognizes every feature name disabled by the sterile command. The exact provider
  process/model rejection is not durably retained by the privacy design, so a correction,
  diagnostic provider call, retry approval, or replacement run requires explicit user direction.
- The Phase 04 sterile command line is byte-for-byte the same command shape as the previously
  successful M13 sterile runner, resolves the same native Codex 0.144 executable, and Terra/High is
  present in the current local model cache. This removes installation, login, command-shape, model
  alias, reasoning support, and disabled-feature spelling from the likely blocker set.
- A provider-free in-memory assembly over the exact durable preview/frozen plans made zero provider
  calls and produced 425 structural chunks, 1,770 ordered events, 693 choices, 425 structural
  sections, and a structural whole-game overview. Existing semantic/derived assembly already does
  the required fallback work; `product_vertical._execution_blocked` returns on terminal
  indeterminate jobs before publication. No product file or project database was changed by this
  proof.

## Remaining lean work

1. Obtain explicit user direction before the bounded composer correction that permits a terminal
   indeterminate run to publish its already-proven structural fallback without another provider
   call. Do not add a provider diagnostic, retry, or replacement run unless separately needed and
   approved after the structural map is inspected.
2. After a published generation exists, inspect representative output and let the user judge it.
3. Perform one final integrated review, focused gates, sharded CI, and one Release/package run.
4. Make PR #30 ready while leaving it unmerged.

## This documentation reset

No product test, provider construction/call, private source access, browser run, CI run, push, PR
mutation, or merge occurred. Protected untracked user/private paths remain untouched.
