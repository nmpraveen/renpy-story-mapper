# M15 MsDay1 Narrative Map correction completion report

Status: In progress

Baseline: `a447a4eefbd7c093bdb2767e62a393805af068ac`

Integration commit: Pending

Pull request: Pending; one PR will be opened and left unmerged for user approval

## Outcome

M15 resumed before integration after the user authorized all future M15 correction and independent-
rereview cycles and removed any coordinator-imposed worker cap. The Track A and Track B heads
remain separate and unintegrated while those cycles run; the done condition and semantic `PASS`
are unchanged. Provider calls remain separately gated.

## Acceptance evidence

| Criterion | Result | Evidence |
|---|---|---|
| 1-5 | Pending | Contract, deterministic corridor/event/map, and provenance evidence pending |
| 6-8 | Pending | Exact private Day 1 semantic and visible-shape evidence pending |
| 9-11 | Pending | Detail/Evidence, visible retirement, and compatibility evidence pending |
| 12-13 | Pending | Durable fake-provider, cache/reopen/resume, zero-call, and consent evidence pending |
| 14 | Pending | 100%/200% browser, keyboard, and layout evidence pending |
| 15-16 | Pending | Authority/source/archive immutability and safety evidence pending |
| 17 | Pending | Focused and full Windows/package validation pending |
| 18 | Pending | Track and final independent reviews pending |
| 19 | Pending | Screenshots, text export, infographic, limitations, and PR state pending |

## Validation

| Command / review | Result | Artifact or notes |
|---|---|---|
| Baseline branch and status | Pass | `main` and `origin/main` matched `a447a4e`; tracked tree clean; unrelated untracked content preserved |
| Exact private source pre-access fingerprint | Pass | SHA-256 `14aa44ed...5d588a6`, 42,818 bytes, `2026-07-20T14:57:21.9287268Z` |
| M11 baseline comparison | Pass | 773 atoms, 165 scenes, nine temporary structures, one chapter, 174 presentation nodes; 115 minimum-run and 35 unresolved-safety boundaries |
| Current-browser baseline at 100%/200% | Pass | `output/playwright/m15-baseline/`; current first page visibly contains repeated `Start`, `Clean`, raw visual titles, old AI/M07 controls, and the M12 route panel; no provider action performed |
| Semantic review | Pass | `SEMANTIC_REVIEW.md` on 2026-07-20 |
| Frozen M15 contracts | Pass | Exact shared head `1ec0664ed6834b79cd1581a3edec7e16225bfc6f`; 7 contract tests passed; targeted Ruff and strict mypy passed |
| Failing-first implementation gate | Pass | Before track implementation, the M15 gate produced the expected 10 failures/1 pass: missing Track A/B interfaces, provider-free acceptance, and browser retirement behavior; the exact source-fingerprint/current-baseline guard passed |
| Track dispatch | Complete | Track A task `019f8042-8627-7780-a515-355056881714` and Track B task `019f8042-8632-7512-a2e3-42ac6932e558` ran in separate worktrees from exact shared head `1ec0664`; both explicitly selected `gpt-5.6-sol` and High reasoning; fast-mode selection was unavailable/unverified |
| Track A corrected candidate | Blocked | Clean head `aa570f3ea7e6cba200cb2585f2f97386128cb07a`; 27 Track A tests, 37 adjacent M10/M11 tests, Ruff, strict mypy over 101 files, diff check, all nine synthetic cases, and exact private acceptance passed; exact rereview retains two P1s |
| Track A exact private acceptance | Pass at unintegrated head | 70 corridors/events, 84 map nodes, 85 map edges, five major clusters, exact choice/rejoin pairs, Terrance end 278 and Janet start 280, required order, no blocked titles, zero provider calls/game execution, and unchanged private fingerprints |
| Track B corrected candidate | Blocked | Clean head `6702e933dba82d19da8ea59ae246020eaebc9e80`; 24 focused/frozen tests, 135 adjacent M13 regressions, 90 reviewer tests, Ruff, strict mypy over 102 files, dependency and diff checks passed; exact rereview retains two P1s |
| Provider/private safety through stop | Pass | Track A used immutable read-only local fixture access; Track B did not access private text; neither task made a cloud/live provider call; no candidate was integrated, pushed, or opened as a PR |
| Phase Coordinator Track A blocker probe | Finding confirmed | Read-only inline CPython 3.12 probe at `aa570f3` passed two corridors with source lines `[2, 1]`, both hard-boundary flags set, and the same incident edge; assembler returned two events instead of failing closed |
| Phase Coordinator Track B blocker probe | Findings confirmed | Read-only inline CPython 3.12 probe at `6702e93` constructed request bounds above the consent limits, submitted a one-call consent twice, omitted a valid claim from the semantic lock when one sibling had unknown evidence, and accepted a replacement claim against that lock |

## Review findings

- Track A rereview `FAIL` at `aa570f3`: `assembly.py` still permits descending hard-boundary
  input when corridors share an incident edge, and the provider-free acceptance runner still
  constructs synthetic corridors or infers parts of exact output instead of proving the full
  corridor-to-event-to-map pipeline.
- Track B rereview `FAIL` at `6702e93`: direct requests can exceed/reuse consent budgets, and
  event-summary repair can replace individually valid claims when a sibling claim is invalid.
- Both first-cycle independent reviewers used `gpt-5.6-sol` High with fast mode
  unavailable/unverified and made no edits. The former one-cycle cap was superseded by the user's
  authorization for all future M15 correction/rereview cycles and platform-permitted workers.
- The narrow Track A correction scope is: reject descending same-context order regardless of
  shared incident provenance; add the shared-edge hard-boundary regression; replace direct
  synthetic `NarrativeCorridor` construction with synthetic M10/M11 inputs passed through
  corridor, event, and map construction; and derive exact cluster order and line bounds from
  event membership/presentation output rather than expected constants.
- The narrow Track B correction scope is: enforce request bounds at or below the manifest;
  consume call grants safely at the provider boundary so a one-call consent cannot submit twice;
  add oversized, sequential-reuse, and concurrent-reuse regressions; and lock every individually
  valid summary claim so an invalid sibling alone cannot authorize its replacement.

## Integration and PR state

- Integrated diff reviewed against contract and exclusions: No
- Required checks passed: No
- Blocking findings resolved or explicitly accepted: No
- PR genuinely ready: No

## Remaining limitations

- Full MsDenvers remains unvalidated and outside M15.
- All future M15 correction and independent-rereview cycles are authorized, with no coordinator-
  imposed worker cap. No integration or Track C dispatch is permitted until both A and B pass.
- Live Day 1 AI acceptance is not authorized and is optional; no provider call has occurred.
- Product implementation, track reviews, final browser/Windows acceptance, infographic, and PR are
  pending.

Complete the native Codex goal only when `PR genuinely ready` is `Yes` and the rows above contain
durable evidence.
