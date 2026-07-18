# M13 optional AI narrative layer completion report

Status: Historical prior PR-ready report; current additional correction is Verification-blocked
by one independent-rereview P1 on existing PR #23

Baseline: `f67df8a7cb805bf4adf8590585bae700d2f3117f`

Runtime freeze: `3533d49a61e77c76794b4ba8338ccf60ee8201ef`

Pull request: [PR #23](https://github.com/nmpraveen/renpy-story-mapper/pull/23) remains open and
unmerged. It is currently non-draft and clean remotely. Current-head review and live/replay gates pass;
reconciled evidence commit `d5fdcaa3a0a15db05f232171754216093cadd026` was pushed and remotely
verified, and unbounded GitHub Release run `29604661539` passed at branch head
`7bf54042639a781313cf6c924e09a0ee023a86f2`, before final lifecycle closeout. Merge always
requires separate approval.

## Outcome

Current final-correction note: multiplicity correction `18f2edf` and exact nontransmission
correspondence correction `ba71cda` pass their failing-first reservation cases, 57 combined
workflow/scheduler tests, Ruff, strict mypy, and diff checks. Independent exact-head rereview is
`PASS` with no P0/P1/new P2. Final Windows Release passes 1,135 tests with 7 hardware-sensitive
deselections plus every quality/build/package gate. Existing PR #23 update and remote verification
remain before the current lifecycle can return to `PR ready`; no provider/live rerun or merge was
performed.

Current additional-correction note: failing-first correction `a7e242b` closes the one-reservation
reopen case and passes 54 workflow/scheduler tests, Ruff, strict mypy, and diff checks. Independent
rereview nevertheless returned `FAIL` with one P1 and no P0/new P2: multiple compatible durable
reservations for the same historically reused logical attempt are collapsed to one recovered
history slot, allowing a third submission under a ceiling of two. The authorized additional
correction/rereview is consumed. The Release run was stopped after this verdict; no push, PR
mutation, provider/live transmission, browser/private-scale/GitHub acceptance, merge, or M14 work
followed. M13 remains in Verification and PR #23 is not ready.

Current lifecycle note: the final correction tracks integrated at `9ab1dbd`, and focused
verification at lifecycle head `532eefc933460ed1876a715df1b12a921e24b3c0` passed 227 tests,
Ruff, strict mypy, JavaScript syntax, and diff checks. Final independent review returned `FAIL`
with one P1 and no P0/new P2: an unresolved reservation is conservatively charged but does not
consume the per-job total-attempt ceiling after reopen. Findings 1 and 3-8 pass, including finding
6 as a proved false positive. All prior evidence below remains historical evidence for its named
head and must not be presented as proof of the pending corrected head.

Track A already used the handoff's one bounded correction and rereview, so no second product loop
was started. The corrected local head was not pushed; Release, browser, private-scale, GitHub,
provider/live, PR mutation, merge, and M14 actions were not performed. The current done condition
is unmet pending explicit authorization for one additional narrowly bounded correction.

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

## Current correction acceptance

This table is historical prior-cycle evidence and is not acceptance of lifecycle head `532eefc`.
Current final review is `FAIL` with the P1 recorded above.

| Gate | Result |
|---|---|
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
| 23 | Pass | Evidence and infographic are durable; explicitly approved draft PR #23 is open and unmerged |

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

## Closeout state

- Current local/runtime/browser/private gates pass at `3533d49`; targeted review passes at
  `e79384b`; approved final-head live/replay passes at `677d881`.
- Native task/goal `019f7048-93db-7383-a869-fc4c78939994` reached its authorized done condition
  after unbounded GitHub Release run `29604661539` passed and this PR-readiness reconciliation.
- Existing PR #23 is open, non-draft, and unmerged. Do not merge PR #23, perform another live
  provider transmission, or begin M14.
