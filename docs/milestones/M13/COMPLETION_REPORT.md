# M13 optional AI narrative layer completion report

Status: Verification for post-merge corrective PR #24; exact PR-head CI pending

Baseline: merged PR #23 commit `d37fe236d576eea553fb7aef9ecc2c5b6c2e0c5a`

Historical pre-merge runtime freeze: `3533d49a61e77c76794b4ba8338ccf60ee8201ef`

Pull requests: [PR #23](https://github.com/nmpraveen/renpy-story-mapper/pull/23) is merged at
`d37fe236d576eea553fb7aef9ecc2c5b6c2e0c5a`. Corrective
[PR #24](https://github.com/nmpraveen/renpy-story-mapper/pull/24) is open as a draft from
`codex/m13-post-merge-usage-recovery`. Merge always requires separate approval.

## Post-merge corrective outcome (current)

Product candidate `a71d5888d55d0d5a19ddb84efd522dccdcbe282d` corrects cross-phase
interruption/reopen accounting without broadening M13. Prior cumulative and current durable usage
remain provenance-separated; disjoint calls/tokens/elapsed/known cost add once; peak is a maximum;
estimated is monotonic; unknown cost fails closed. Exact checkpoint coverage prevents double count,
adds later events once, and now validates its stored aggregate against the covered events before any
cache/admission/submit boundary. Legacy ambiguous usage remains cache-readable but cannot authorize
a miss.

The parent focused matrix passes 97 tests. Track A Reviewer A, Track B, and final Track C pass with
no P0-P3. Track C's earlier `CHANGES REQUESTED` at `5c792c1` is preserved as historical failing
evidence and is closed by failing-first `bd46caf` plus correction `a71d588`. The single authorized
local Windows Release passed at `5c792c1` with 1,149 passed and 7 hardware-sensitive deselections,
plus every quality/build/package gate. It was not repeated after the final two-file correction;
exact corrected-head focused tests and independent reviews pass, and full exact PR-head CI remains
the final PR-readiness gate.

No provider/live transmission, browser/private-scale rerun, merge, M14, destructive cleanup, or
protected-path action occurred. Historical browser UI/static facts remain inheritable; prior live,
browser retry/reopen accounting, private-scale accounting, and replay counts remain exact-head
history only.

## Historical pre-merge PR #23 outcome

At the final pre-merge correction checkpoint, multiplicity correction `18f2edf` and exact nontransmission
correspondence correction `ba71cda` pass their failing-first reservation cases, 57 combined
workflow/scheduler tests, Ruff, strict mypy, and diff checks. Independent exact-head rereview is
`PASS` with no P0/P1/new P2. Final Windows Release passed 1,135 tests with 7 hardware-sensitive
deselections plus every quality/build/package gate. Product/evidence head `120a4ec` was pushed and
remotely verified on PR #23. At that checkpoint M13 was `PR ready`; no provider/live rerun or merge
was performed.

Historical additional-correction interim note: failing-first correction `a7e242b` closes the one-reservation
reopen case and passes 54 workflow/scheduler tests, Ruff, strict mypy, and diff checks. Independent
rereview nevertheless returned `FAIL` with one P1 and no P0/new P2: multiple compatible durable
reservations for the same historically reused logical attempt are collapsed to one recovered
history slot, allowing a third submission under a ceiling of two. The authorized additional
correction/rereview is consumed. The Release run was stopped after this verdict; no push, PR
mutation, provider/live transmission, browser/private-scale/GitHub acceptance, merge, or M14 work
followed at that interim point. The later authorized multiplicity correction and rereview resolved
this finding as recorded above.

Historical cross-track lifecycle note: the final correction tracks integrated at `9ab1dbd`, and focused
verification at lifecycle head `532eefc933460ed1876a715df1b12a921e24b3c0` passed 227 tests,
Ruff, strict mypy, JavaScript syntax, and diff checks. Final independent review returned `FAIL`
with one P1 and no P0/new P2: an unresolved reservation is conservatively charged but does not
consume the per-job total-attempt ceiling after reopen. Findings 1 and 3-8 pass, including finding
6 as a proved false positive. All prior evidence below remains historical evidence for its named
head and must not be presented as proof of the pending corrected head.

At that interim point Track A had already used the handoff's one bounded correction and rereview,
so no second product loop was started. The user later supplied the separately recorded narrow
authorization that produced the current passing correction and rereview.

The authorized bounded-correction runtime is frozen at `3533d49`. Exact M12 result/path/scene/
hierarchy authority, compatible durable resume, cumulative and failed-call accounting, browser
provider-settings binding, shared privacy validation, and exact citation navigation through the
existing Detail/Evidence workspace are integrated. Current focused M13, adjacent M12/persistence,
Windows Release, real-Chrome 100%/200%, and fresh 1,812-scene provider-free private-scale gates
pass. The sanitized current index is `docs/milestones/M13/CURRENT_EVIDENCE.json`.

Independent targeted review at exact integrated head `e79384b` passed with no P0/P1/new P2. The
subsequently approved production-path live run/replay at exact head `677d881` passes criterion 20:
all 90 eligible jobs publish through the complete route-aware hierarchy, and exact fail-closed
replay makes zero submit attempts/calls/tokens while reproducing hashes/rendering. Source and
authority are unchanged and privacy inspection is clean. The user-authorized unbounded GitHub
Release check passed 1,081 tests with 7 deselections and all quality/build/package gates green;
M13 is `PR ready`.

## Historical pre-merge correction acceptance

The earlier full-stack evidence remains exact-head evidence. The narrow provider-free recovery
change is accepted by its failing-first regressions, exact-head independent rereview, and final
Windows Release.

| Gate | Result |
|---|---|
| Final recovered-reservation correction | `18f2edf` and `ba71cda`; failing-first multiplicity/nontransmission cases; 57 workflow/scheduler tests; Ruff and strict mypy pass |
| Final independent rereview | PASS at exact `ba71cda`; no P0/P1/new P2 |
| Final Windows Release | 1,135 passed, 7 hardware-sensitive deselected; all quality/build/package gates green |
| Historical PR #23 checkpoint | Product/evidence head `120a4ec` was verified open, non-draft, mergeable, and `CLEAN`; no configured status checks |
| Runtime and local/Windows | Runtime `3533d49`; focused M13 291/1, adjacent M12+persistence 139/1, Release 1,079/7 and all quality/build/package checks pass |
| Browser and private scale | Chrome 100%/200% passes with zero navigation/provider calls; 1,812-scene private-scale simulation passes with exact zero-call replay |
| Independent review | PASS at `e79384b`; no P0/P1/new P2; detached clean zero-edit review |
| Approved final-head live/replay | PASS at `677d881`; 24 calls, 90 publishable jobs, complete hierarchy, 1,035 audited claims; exact replay zero calls; report `f97bbfec...313f` |
| Unbounded GitHub Release | PASS run `29604661539` at `7bf5404`; 1,081 passed, 7 deselected; all quality/build/package gates green; no local rerun |

## Historical pre-correction acceptance evidence

The following table records the previously accepted `740e321`/`0aa0415` state. It is not current-
head proof for the reopened correction areas.

| Criteria | Result | Evidence |
|---|---|---|
| 1-13 | Local pass with independent review | Runtime `740e321`; focused 61-test matrix, Release 1,015/7, and no-P0/P1 review pass |
| 14-16 | Pass | Public canary, exact stable consent, finite budget/no-retry live run, privacy, and provider identity pass |
| 17-19 | Pass | Chrome 100%/200% and complete 1,812-scene provider-free/private simulation |
| 20 | Pass | Exact approved live run completed the route-aware hierarchy; fail-closed exact replay made zero submit attempts/calls and reproduced hashes/rendering exactly |
| 21 | Pass | Source and M10/M11/M12 authority unchanged; no unauthorized remote/game action or raw-debug retention |
| 22 | Pass | Post-correction Release 1,016/7, focused correction, final-budget review, and post-live audit pass with no unresolved P0/P1 |
| 23 | Pass | Evidence and infographic were durable; explicitly approved draft PR #23 was open and unmerged at that checkpoint |

## Historical validation snapshot

| Check | Result |
|---|---|
| Focused final model-identity/consent/provider matrix | 59 passed; Ruff, strict mypy, whitespace passed |
| Full Windows Release | 1,015 passed, 7 deselected; all quality/package gates passed |
| Post-correction Windows Release | 1,016 passed, 7 deselected; all quality/package gates passed |
| Provider-free private scale | Passed at `740e321`; report SHA-256 `13226a0d25cff4a63d33f8bdd9d8e1a13f19d2f36a51c0c9e1003cd6a832b0dc` |
| Chrome 100%/200% | Passed; report SHA-256 `dd873f0fcaa6532c317fef982a366b94151864052d27458c45803dddf7691437` |
| Live preview | Corrected zero-submit preview SHA-256 `a2fbe4acae8be57e11ef9560a72dc9aa3431df5d95a177f319ecd1ad9063e996` |
| Live run/replay | Passed; report SHA-256 `93a22d669d625b8366f47792d13a7dac98db1c8bab1f7f85bd0a77b46d81a621`; 13 calls for live execution and zero submit attempts/calls for exact replay |
| Independent review | Final-budget PASS at `740e321`; no P0/P1 |
| Native milestone infographic | Complete; SHA-256 `7ac430f485f26956b271268ad8c6f63cd6d403e8570d837d2cd1f28123c98d3d` |

## Historical PR #23 closeout state

- At PR #23 closeout, the final correction passed through `ba71cda`; final rereview had no
  P0/P1/new P2; Windows Release passed 1,135/7 and every quality/build/package gate.
- Native task/goal `019f7264-0e92-7e33-a372-ee81de102ab8` owns this final done condition.
- Product/evidence head `120a4ec` was remotely verified on PR #23. At that checkpoint the PR was
  open, non-draft, mergeable, `CLEAN`, and unmerged, with no configured status checks.
- PR #23 later merged at `d37fe236`; another live provider transmission and M14 remain excluded.
