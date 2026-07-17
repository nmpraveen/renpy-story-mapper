# M13 integrated and independent review report

Status: PASS for bounded current-head targeted review and final live/replay acceptance; no P0/P1

Runtime freeze: `3533d49a61e77c76794b4ba8338ccf60ee8201ef`

Review date: 2026-07-17

## Current authorized correction review

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
remaining lifecycle step is the authorized update and remote verification of existing PR #23.

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
