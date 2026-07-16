# M13 optional AI narrative layer completion report

Status: Verification in progress

Baseline: `f67df8a7cb805bf4adf8590585bae700d2f3117f`

Validated product commit: `859328e1cbe8933809bd49001d681d1f7f6701d4`

Pull request: Not created; explicit user approval is required

## Outcome

The release-critical M13 implementation is integrated. The optional browser Narrative layer now
binds exact M10/M11/M12 authority to independent durable scene jobs, validates and salvages claims
individually, batches only provider transport, reduces bounded artifacts through a deterministic
segment fan-in tree, preserves mutually exclusive routes, stores a lazy claim DAG, and presents
coverage, jobs, consent, citations, and route-aware hierarchy artifacts without changing or
requiring the deterministic product.

Provider-free private-scale acceptance, real Chrome acceptance, and the full Windows release suite
pass. M13 is not yet PR ready: the prepared live-provider sample requires exact manifest consent,
a separately configured independent review remains, and final evidence reconciliation must be
completed. The native infographic is complete. No PR has been created.

## Acceptance evidence

| Criteria | Result | Evidence |
|---|---|---|
| 1-13 | Pass | `VALIDATION_REPORT.md`; contracts, authority, validation, batching, persistence, segments, hierarchy, contradiction, and pipeline tests |
| 14-16 | Pass in provider-free/mocked acceptance | Sterile provider, consent, budget, identity, prompt, and privacy tests; live call pending exact consent |
| 17-19 | Pass | Real Chrome 100%/200%; complete current private-corpus simulation and exact zero-call replay |
| 20 | Pending | Exact prepared live manifest has made zero submissions and awaits user confirmation |
| 21 | Pass for completed acceptance | Authority and private-input snapshots unchanged; zero execution and unauthorized remote counters |
| 22 | Partial | Release suite passed; separately configured independent review pending |
| 23 | In progress | Reports/product commit and native infographic durable; final PR-readiness reconciliation pending |

## Validation

| Command / review | Result | Artifact or notes |
|---|---|---|
| Focused final authority and hierarchy set | 62 passed | Claim validation, contradictions, hierarchy, reductions, pipeline, provider, and API |
| Full Windows release suite | 951 passed, 7 deselected | Ruff, strict mypy over 91 files, `pip check`, JavaScript, package build/install/import/assets/notices passed |
| Provider-free private-scale acceptance | Passed | 1,812 scenes; report SHA-256 `351b952e5f7dba443190202fa2461b3f41f3b70e2870dbbc9ff9820f7f095279` |
| Bounded live/private acceptance | Awaiting exact consent | Preview SHA-256 `50fe3389870e568a409f0cb9de13fc8f12dfc75e1c6636c5982e64396ba085e9`; zero submissions |
| Real Chrome 100%/200% | Passed | Report SHA-256 `2b938d37b152456cf3646f23ebda98d73ccc79c79379394ec35aa4df01a88273` |
| Native milestone infographic | Complete | `INFOGRAPHIC.png`, SHA-256 `7ac430f485f26956b271268ad8c6f63cd6d403e8570d837d2cd1f28123c98d3d` |
| Independent review | Pending | Current primary adversarial report is not represented as independent |

## Review findings

- Three P1 findings were corrected in `859328e`: contradiction enforcement at publication,
  bounded Detail/Evidence handling for large exact M12 citations, and exact M12 factual semantic
  preservation in hierarchy claims.
- No P0 or P1 finding remains from the integrated primary adversarial pass.
- `REVIEW_REPORT.md` records why a separately configured independent pass is still required.

## Integration and PR state

- Integrated diff reviewed against contract and exclusions: Yes, in the primary adversarial pass
- Provider-free, private-scale, browser, package, and full Windows checks passed: Yes
- P0/P1 findings from the primary pass resolved: Yes
- Exact consented live acceptance complete: No
- Separately configured independent review complete: No
- PR genuinely ready: No

## Remaining limitations

- Exact live-provider acceptance is approval-gated by the prepared consent manifest. Completed
  local work remains durable, and no provider call has occurred.
- A correctly configured read-only external-model review was rejected before transmission because
  it would send private repository code outside the machine. Independent review remains a release
  gate and requires explicit informed user approval; no workaround was attempted.
- Optional weak-boundary suggestions, LM Studio/local-provider integration, and export polish are
  deferred. Their absence does not block the core M13 hierarchy.
- At most one targeted repair is supported. The default scheduler favors claim-local salvage and
  independent item retry and does not automatically spend a repair call.

Complete the native Codex goal only when `PR genuinely ready` is `Yes` and the rows above contain
durable evidence.
