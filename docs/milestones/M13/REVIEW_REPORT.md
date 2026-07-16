# M13 integrated adversarial review

Status: Primary pass complete; separate independent review pending

Reviewed range: `f67df8a7cb805bf4adf8590585bae700d2f3117f..859328e1cbe8933809bd49001d681d1f7f6701d4`

Review date: 2026-07-16

## Scope

The primary review re-read the approved M13 contract and challenged authority binding, evidence
ownership, M12 language preservation, route separation, contradiction identity, partial salvage,
batch isolation, provider process policy, consent, storage privacy, cancellation durability,
cache replay, bounded hierarchy fan-in, browser evidence, and private-scale behavior.

## Findings

| Severity | Finding | Disposition |
|---|---|---|
| P1 | Context-aware contradiction checks existed as a utility but were not enforced while publishing accepted claims | Fixed in `859328e`; factual conflicts are salvaged claim-locally and interpretive disagreements remain warnings |
| P1 | An exact but oversized M12 citation could make the evidence endpoint fail closed instead of returning a bounded view | Fixed in `859328e`; the endpoint returns a deterministic hash-bound bounded projection and keeps lazy exact resolution |
| P1 | Higher-level factual prose needed a stronger invariant against upgrading exact M12 status/prerequisite semantics | Fixed in `859328e`; an M12 factual C-handle must preserve one exact leaf's text and normalized semantics |

No unresolved P0 or P1 finding remains from this primary review. Focused regressions, the full
release suite, complete private-scale simulation, and real Chrome acceptance passed after the
corrections.

## Independence statement

This document is deliberately not labeled an independent review. The repository requires review
dispatch with explicit `gpt-5.6-sol`, high reasoning, and fast mode disabled. The current
collaboration controls do not expose or verify those selectors. A separately configured read-only
review of the literal final integration head remains a release gate; its findings and commands
must be appended before M13 is marked PR ready.
