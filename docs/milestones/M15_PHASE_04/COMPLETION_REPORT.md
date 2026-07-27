# M15.1 Phase 04 progress report

Status: Verification — the structural full-game map is published and final lean gates are in progress

Current product checkpoint: `157c496` on `codex/m15-phase04-full-game`

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

## Gate 3 publication and live acceptance

- The user authorized the narrow completion path. Visible worker task
  `019fa38c-0524-7eb1-9ccf-4dedc9189af9` used explicit `gpt-5.6-sol` with Medium reasoning; the
  dispatcher still exposed no fast-mode selector, so fast mode remains unavailable/unverified.
- Five demonstrated seams were corrected without new schemas, protocols, provider calls, or broad
  hardening: terminal structural publication (`3cdc7e6`), omission of reader effects rejected by
  the existing privacy validator (`3ec5f93`), complete reader bootstrap discovery (`afe9157`),
  exact-ID-first and unique-locator evidence compatibility (`13c82d4`), and the existing frontend's
  relative locator projection (`157c496`).
- A pre-publication backup was made before the frozen project changed. Provider-free publication
  constructed no provider and activated complete generation
  `b7f05d2c33799f8e214a3b9e927fff46a88baa5aa00d9090a3b782fb3371f940`, map revision 1.
- Published counts are 425 sections, 1,770 events, 693 choices, 719 arms, 163 endings, and 59
  landmarks. The historical workflow remains honest: 425 calls, zero accepted AI results, 19
  structural results, 406 indeterminate results, and zero reported tokens.
- Live Chrome at 1600x900 opens Story Map V2 directly. It renders all 425 section controls, nested
  choice `Clean`, persistent state/effect pills, deterministic Path, final section `425.1` with a
  late state assignment, and HTTP 200 Detail/Evidence showing the relative locator
  `game/v0.01_clean.rpy:5 · physical`. Durable pages contain 163 items explicitly typed `ending`.
- Normal and effective-200 screenshots show no obvious horizontal overflow. Console output is
  limited to the known meta-CSP `frame-ancestors` warning and missing favicon; all reader API
  requests used loopback and returned HTTP 200.
- AI summary prose is not present because the approved provider run produced no accepted results.
  Sections and events therefore use explicit structural fallback language. This is accurate but
  repetitive; the user must still decide whether the real output is useful enough for quick
  personal story checking.
- The five protected archives remain unchanged after acceptance: 2,608,378,896 bytes, aggregate
  SHA-256 `b880f1529834c15aace56a8b7701f716b68e3bc90cb721bf1029a15ad11c3a86`
  before and after using sorted `name|size|sha256` records. `scripts.rpa` remains 2,140,282 bytes
  with SHA-256 `053abb13454180a2cf9b0aa762e33deda98cf027d9c1e39082f5795982720303`.
- The final focused integration gate passed 120 tests in 38.16 seconds across product composition,
  derived semantics, workflow HTTP v2, reader API, and real-browser fixtures. The final projection
  seam additionally passed its focused test, Ruff, strict mypy, and whitespace check.

## Remaining lean work

1. Obtain the one independent integrated review verdict with no unresolved P0-P2.
2. Run the one final Windows Release/package gate on the product/evidence candidate.
3. Push once, inspect the repository-wide sharded CI once, and leave PR #30 open and unmerged.
4. Obtain explicit user approval that the supplied normal/effective-200 result is useful. Do not
   mark Phase 04 complete or PR #30 ready before that subjective gate.

## This documentation reset

No product test, provider construction/call, private source access, browser run, CI run, push, PR
mutation, or merge occurred. Protected untracked user/private paths remain untouched.
