# M13 integrated and independent review report

Status: PASS for the final duplicate-reservation rereview; no P0, P1, or new P2

Runtime freeze: `3533d49a61e77c76794b4ba8338ccf60ee8201ef`

Current correction head: `ba71cda82eba2e605f97041923329ee9afd2a681`

Review date: 2026-07-17

## Final duplicate-reservation rereview (current)

Independent reviewer `/root/m13_multiplicity_rereview` reviewed exact clean head `ba71cda`, ranges
`58ba7ed..18f2edf` and `18f2edf..ba71cda`, and returned `PASS` with no P0, P1, or new P2. The
reservation-focused set passed 5, workflow/scheduler passed 57, and Ruff, strict mypy, and range
diff checks passed.

Provider-free probes confirmed one-to-one matching: positive calls require exact batch/job/attempt/
provider-call identity; zero-call attempts cover only one unresolved or explicitly nontransmitted
matching reservation. Unmatched reservation multiplicity is preserved, cumulative usage is not
double-counted, total/subtype ceilings remain enforced, and compatibility, idempotency, and cache
behavior remain green. Review was read-only with no provider/live, private, network/GitHub, PR,
push, merge, or M14 action. Sol/High was selected; fast-mode selection was unavailable/unverified.

## Historical additional recovered-reservation rereview

Independent reviewer `/root/m13_reservation_rereview` reviewed exact clean head `a7e242b` and
range `a97e10d..a7e242b` read-only. The intended failing-first regression genuinely failed before
the product edit because reserved logical attempt 1 was resubmitted under a total ceiling of 1;
after correction it passes. The full workflow/scheduler pair passed 54 tests, a focused interaction
set passed 23, and Ruff, strict mypy, and diff checks passed.

Verdict: `FAIL`. One P1 remains; no P0 or new P2 was found. `workflow.py` reconstructs recovered
reservations keyed by logical attempt number and suppresses entries already represented by that
number. Multiple compatible unresolved reservations for the same job/attempt are reachable from
the prior defect because the logical attempt number was reused while provider call number and
reservation identity advanced. A provider-free probe seeded two such reservations with
`maximum_attempts_per_job=2`; reopen still submitted the target, allowing a third logical
submission. Recovery must preserve reservation multiplicity or fail closed, while de-duplicating
only the reservation covered by its corresponding persisted attempt.

The review made zero edits and used no provider/live, network/GitHub, private, PR, push, merge, or
M14 action. The collaboration API exposed no fast-mode selector, so fast-mode state remains
unavailable/unverified. The explicitly authorized additional correction/rereview is consumed; no
further product loop was started. M13 remains in Verification and PR #23 is not ready.

## Historical final bounded integrated review

Independent reviewer `/root/m13_final_integrated_review` reviewed exact detached lifecycle head
`532eefc933460ed1876a715df1b12a921e24b3c0`, including correction range `f629e53..532eefc` and
prior-PR range `e17ba5e..532eefc`. Verdict: `FAIL`. One P1 remains; no P0 or new P2 was found.

Recovered unresolved reservations remain conservatively charged to cumulative calls/tokens, but
`workflow.py` rebuilds per-job attempt history only from ATTEMPT rows. Scheduler admission therefore
does not see the reserved logical attempt and assigns `len(history) + 1` again. The provider-free
CPython 3.12 probe seeded unresolved logical attempt 1 with `maximum_attempts_per_job=1`, observed an
empty recovered history, then observed four further provider-stub calls and cumulative calls 1 to
5. This violates finding 2's total-attempt ceiling before every invocation/reopen.

Findings 1 and 3-8 pass, including exact cumulative usage, reservation accounting, pre-execution
browser identity, transmission attestation, unchanged M12 alternative-route authority, recursive
privacy aliases, and all-citation navigation. Finding 6 is a false positive. Focused checks passed
35 tests plus 9 scheduler/provider boundary tests; Node syntax, diff, and exact clean-state checks
passed. Review was zero-edit and provider/network/private/PR/push/merge free.

Track A already consumed the one reviewer-driven correction and rereview permitted by the final
handoff. No second correction loop was started, and the head was not pushed. M13 remains in
Verification pending explicit authorization for one additional narrowly bounded correction and
rereview.

## Historical prior authorized correction review

Independent reviewer `/root/m13_final_targeted_review` reviewed exact integrated head
`e79384bb7d16b93b734a47111981996261047965` and frozen runtime
`3533d49a61e77c76794b4ba8338ccf60ee8201ef` in a detached, clean, read-only worktree. The bounded
scope covered exact M12 authority; durable restart, cumulative budgets/attempts, and failed-call
accounting; provider-settings identity; shared privacy validation; existing-workspace citation
navigation; and durable evidence/lifecycle consistency.

Verdict: `PASS`. No P0, P1, or new P2 was found. Focused offline regressions passed 105 tests;
hierarchy/persistence plus complete M12-bound pipeline passed 32; lifecycle contracts passed 2;
the evidence index parsed; both correction-range diff checks were clean. The reviewer made zero
edits and no provider, web, external, live/private/browser-provider, PR, push, merge, or M14 action.
Dispatch selected `gpt-5.6-sol` and High reasoning; the collaboration control exposed no fast-mode
selector, so fast mode remains unavailable/unverified rather than claimed disabled.

This PASS closes the independent-review gate. No runtime code changed after the frozen review.
The subsequently approved production-path live run/replay at exact head `677d881` also passed:
90 publishable jobs completed the route-aware hierarchy, claim/citation/privacy/immutability audits
were clean, and fail-closed replay made zero submit attempts/calls/tokens with exact hashes. The
reconciled evidence was then pushed and remotely verified on existing PR #23. Review/live gates
remain closed. Unbounded GitHub Release run `29604661539` subsequently passed 1,081 tests with 7
deselections plus every quality/build/package gate at branch head `7bf5404`; lifecycle is `PR ready`.

## Historical review chain

Everything below this heading is historical evidence at its recorded head and does not state the
current `3533d49` verdict.

| Review | Artifact SHA-256 | Result / disposition |
|---|---|---|
| Initial independent review | `4e7fa08bce6658ec7341729cb8cfab60680ab33f8cac7c035f168a870ea308d7` | Four P1s and one P2; corrections began in `04082c0` and later commits |
| First rereview | `ecbb008eaaa1f683eea2037fb4c23b440dca53eabb9837ae8dd178a77e92eef0` | Three P1s: authority cap, final 256 bound, incompatible route/time support |
| Second rereview | `592784d4356da037a79891c1dcd0aca84faf26a06fd25a469ec4dcd15f19ab34` | Three P1s; stale asset manifest fixed by `885905b`, remaining authority/context work continued |
| Corrective rereview `04082c0..9889035` | `be23d6fd6cf85f9e3f8c1ef746839fef993ac1ab40f46d45fd3a4650b0120a23` | FAIL: two P1s; exact report/settings in `CORRECTIVE_REREVIEW_REPORT.md` |
| Single permitted corrective cycle | Commit `e0fd3bf` | Local focused/Release/private/browser gates pass; no second independent review was authorized |
| Live acceptance observation | `LIVE_ACCEPTANCE_FAILURE.md` | New P1: previewed consent ID changes when consent is granted; live provider acceptance also failed |

The corrective reviewer ran as external session `019f6d01-2c81-71c0-b459-d2a99ccc5be7`
with model `gpt-5.6-sol`, reasoning `high`, `--disable fast_mode`, `--sandbox read-only`, ignored
user config/rules, strict config, and ephemeral persistence. It did not edit files or run the full
suite.

## Corrective rereview findings and one-cycle dispositions

| Severity | Finding at `9889035` | Single-cycle disposition at `e0fd3bf` |
|---|---|---|
| P1 | Exact M12 route context could be replaced by unrelated child context, and deterministic salvage re-atomized inherited scope | Exact factual M12 claims now cite only one exact authority child; deterministic proxies preserve inherited scope; direct regressions pass |
| P1 | Schema-valid 256-claim output could overflow/abort after mandatory authority insertion | Mandatory representations are deterministically deduplicated by authority ID; invalid duplicates are claim-locally salvaged; 256-item adversarial regression passes |

The focused M13 set passed 70 tests and Release passed 966/7 after these changes. This is strong
local closure evidence, but it is not an independent PASS at the final head.

## New blocking finding from live acceptance

| Severity | Finding | Evidence / required disposition |
|---|---|---|
| P1 | Consent identity is not stable across the exact approval boundary: `ConsentManifest.manifest_id` hashes `consent_granted`, so granting the approved preview creates a different ID for persisted provider requests | Preview `m13_consent_3bb95e...`; transmitted/granted run `m13_consent_d2b91d...`; stop under the one-cycle rule and require a separately approved future correction/review |

The live provider also returned only sanitized transient failures: 74 failed jobs, 222 attempts,
24 calls, zero tokens, and no artifacts/replay. That is an acceptance blocker but does not by itself
identify a runtime-code cause.

## Deferred lower-severity item

The initial P2 concerning title/summary evidence binding remains documented and deferred under the
contract's P2 policy. No optional weak-boundary, LM Studio, export, or M14 scope was added.

## Historical verdict at `e0fd3bf`

`FAIL` for PR readiness. P1 blocks remain: unstable exact-consent identity and no independent
final-head PASS; criterion 20 also lacks a successful live run and zero-call replay. No second
correction/review loop was started.
