# M15.1 Phase 04 closeout report

Status: PR preparation — partial functional checkpoint accepted for closeout

Current product checkpoint: `f25e8c0` on `codex/m15-phase04-full-game`

Pull request: #30, open and unmerged; update/ready operation follows this evidence commit

## Closeout decision

On 2026-07-27 the user chose to send the current Phase 04 state as the PR and close this phase.
The checkpoint delivers the local-only 425-summary workflow, durable progress/transcript visibility,
and the existing reader/path/evidence seams. It does **not** match the earlier mock's concise
day/chapter/major-event information architecture: the reader still exposes 425 chunk-level sections
and some path steps remain technical. That redesign is explicitly deferred to a separately scoped
follow-up rather than claimed as completed Phase 04 work.

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

## Final correction, review, and Release evidence

- The first Release diagnostic ran through every stage and exposed exactly three repository
  contract failures after 1,770 tests passed: the new Phase 04 tests were missing from the explicit
  shard inventory, lifecycle assertions still expected `Blocked` and an accessible native goal,
  and Story Map V2 transitively imported the historical narrative stack through concrete Project
  and M12 loaders. All other Release stages passed.
- Commit `c34340a` adds measured timings for the ten Phase 04 files, deterministically rebalances
  the four explicit CI lanes, and makes the lifecycle test assert the truthful `Verification` and
  `goal: null` state. The shard/lifecycle correction gate passed 23 tests.
- Commit `4484460` keeps concrete Project opening and M12 authority loading at the web composition
  boundary; Story Map V2 now accepts a small opened-project protocol plus injected authority and
  opener. The architecture test was not weakened. Its worker gate passed 59 focused tests, Ruff,
  strict mypy over 130 source files, and whitespace.
- The corrected integrated gate passed 153 tests in 43.65 seconds, Ruff over source/tests/scripts,
  strict mypy over 130 source files, and the complete `2bcdd02..4484460` diff check.
- The same independent reviewer closed its sole earlier P2 and returned `PASS` at exact
  `44844601bd46669759ae808be694323e8ad24033`: P0=0, P1=0, P2=0. Its correction rereview passed
  48 focused tests plus the exact transitive architecture test, Ruff, mypy, and diff checks; the
  review worktree stayed clean and no private input/provider/PR state was touched.
- Final Windows Release/package validation passed on product candidate `4484460`: 1,773 tests
  passed, one real-Chrome scale matrix was explicitly skipped because its opt-in environment flag
  was not set, and 16 hardware-sensitive tests were deselected. Ruff, strict mypy, dependency,
  JavaScript, whitespace, isolated sdist/wheel build, install/import, browser asset, and notice
  checks all passed in 609.9 seconds.

## Local-only summary observability and prompt correction

- The user requested a private record of every model prompt/response and a more detailed website
  progress view. Commit `4426a58` adds an opt-in JSONL transcript outside durable project storage
  and Git. Each model call records its full parsed prompt/response, identity, accounting, outcome,
  and validator comment. Transcript write failure cannot change workflow behavior.
- The website now has one collapsed `AI progress details` table using the existing preview/status
  response. It labels all 425 ordered queries by story section/part and shows response, summary,
  and comment state without adding an HTTP route, schema, database table, or dashboard.
- A bounded local-only experiment compared the former exact-mechanics prompt, one event per Python
  atomic group, and one whole-chunk event. The selected whole-chunk variant used 150 output tokens
  and 4.86 seconds on the same first real chunk, versus 1,701 tokens and 44.58 seconds for the
  16-event variant. Python now attaches exact placements, choices, effects, routes, rejoins, and
  endings, and trims prose to existing bounds.
- The cancelled diagnostic run proved the two remaining validators were false format failures:
  Python-owned escaped Ren'Py dialogue in canonical mechanics was mistaken for a Windows path, and
  three otherwise valid summaries exceeded 320 characters. The correction excludes only
  Python-owned canonical mechanics from the provider-material scan and keeps the existing path/raw
  packet checks over provider prose.
- Fresh zero-submit preview disclosed `lm-studio-loopback`, model
  `qwen3.5-35b-a3b-uncensored-hauhaucs-aggressive`, reasoning none, fast mode unspecified, private
  story only to the local provider, 425 jobs, and the historical 2,927 maximum-call bound. The
  corrected local run completed with 425 accepted mapping summaries, zero failed jobs, and zero
  structural placeholders. No cloud AI was used.
- Commits `2f5395b` and `68cfd9b` keep review flags and event keys in Python. Commit `299bfe9`
  publishes the accepted 425 local mapping summaries directly through the existing Python-owned
  hierarchy instead of scheduling another 425 section calls plus rollups. The final projection
  rebuild reused all 425 durable cache hits and made zero model calls.
- Commit `f25e8c0` uses the already-accepted event prose for the section labels and overview, caps
  the 425-item section index, and lazy-loads the full 425-row query/result table after a browser
  refresh. Live Chrome verified rows 1 through 425, meaningful Day 1 labels/prose, and active
  complete generation `cf5f7daa9b62fe7c0eedd23964881329bbf60f9a1a03ed67415665b78104f3a6`.
- Exact current-head focused verification passed 147 tests in 28.33 seconds plus Ruff, strict mypy,
  JavaScript syntax, and whitespace. A consolidated ordered transcript with all 425 complete local
  prompts/responses and an index/run note are under
  `output/m15-phase04-local-summary-final-mapping-only-20260727-184342/` and are not committed.

## Closeout verification

- Focused current-head workflow/browser gate: 136 passed in 29.06 seconds.
- Tracked Phase 04 diff: Ruff passed; strict mypy passed over 11 changed source modules; JavaScript
  syntax and whitespace passed.
- Full Release run: 1,781 passed, one opt-in Chrome scale test skipped, and 16 hardware-sensitive
  tests deselected. The only failure was three stale asset-manifest hashes after web changes; all
  remaining quality and package stages passed.
- Exact corrected head: the deterministic asset-manifest regression passed, followed by isolated
  sdist/wheel build, install, import, browser-asset, and notice verification passing.
- No additional broad rerun was started solely to repeat the already-passing 1,781-test body; the
  pushed PR's sharded checks are the exact-head full verification authority.

## Deferred follow-up

Create a separately scoped milestone only when requested for semantic day/chapter/major-event
grouping and a mock-like reader presentation. Do not reopen Phase 04 or treat this deferral as a
hidden acceptance pass.

## Current checkpoint boundaries

The final local projection rebuild made zero model calls and no cloud request. Raw private
prompt/response evidence remains outside Git. No private output, source archive, or prompt/response
transcript is included in the closeout commit, and PR #30 remains unmerged.
