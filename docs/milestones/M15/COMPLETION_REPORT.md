# M15.1 semantic Story Map correction report

Status: In progress

Correction base: `55ae57406cfb07a3c088d0dfd7c3b7e04ca9a719`

Integration branch: `codex/m15-msday1-narrative-map`

Pull request: [PR #26](https://github.com/nmpraveen/renpy-story-mapper/pull/26), open and unmerged.

## Current outcome

The user rejected the prior M15 Story Map because it presented a wide generic engineering graph
rather than a compact human-readable narrative. The previous `PR ready` status is revoked. M15.1 is
a correction inside the same milestone, branch, and PR; it is not complete and no prior screenshot,
visible-order export, review, provider-free map, Release run, or passing PR head satisfies the new
contract.

The corrected implementation and supported product path are integrated locally and independently
reviewed. The first approved live boundary run failed safely with no validated jobs, exposing an
unsupported response-schema keyword. Versioned successor schemas preserve old identities and local
validation while removing that provider-incompatible keyword. Correction gates, a fresh boundary
run, the separate summary stage, final private evaluation, user visual approval, and the final
Release/PR gate remain pending.

## Evidence status

| Area | Status | Evidence |
|---|---|---|
| Branch and PR identity | Complete | Local and remote branch head matched the correction base; PR #26 was open, non-draft, mergeable, and unmerged at preflight |
| Private-input preflight | Complete | Source and archive SHA-256, size, and timestamps matched the private manifest; private materials remain ignored and unstaged |
| Revised contract | Complete | `GOAL.md` defines fine semantic units, exhaustive boundaries, deterministic hierarchy, two-stage live production, compact vertical UI, and corrected acceptance gates |
| Revised semantic gate | Complete | `SEMANTIC_REVIEW.md`: `PASS` on 2026-07-21 |
| Replacement native goal | Complete | Goal `019f8014-e8f9-7af3-a54f-8cc3a7e7149c` is active with the exact revised done condition and remains active through genuine PR readiness |
| Shared failing-first freeze | Complete | Exact head `c768b19c8d9364db8f1987cb420e69ac0c2e535d`; 14 passing contract/workflow checks, Ruff, strict mypy, and 7 expected track-owned failures |
| Tracks A/B/C and exact-head reviews | Complete | Track A reviewed head `09062370`; Track B final supported product-path head `ca048973`; Track C final compatibility head `61a3eef`; all required exact-head reviews passed with no unresolved P0-P2 |
| Integrated fake-provider acceptance | Complete | Local integration head `4f6f740`; 174 M15 passed/2 expected opt-in skips, 169 compatibility passed, both enabled Chrome suites 10 passed, Ruff, strict mypy over 114 files, JavaScript syntax, whitespace, and private-reference diff scan passed |
| Provider-schema correction | Complete and independently reviewed | Four versioned successors preserve historical resources and remove only unsupported `uniqueItems`; all four current/stale routes and all eight delegated uniqueness sites have direct regression coverage. Independent re-review passed with no P0-P2. 184 M15 passed/2 expected opt-in skips, 169 compatibility passed, enabled Chrome 10 passed, Ruff, strict mypy over 114 files, JavaScript syntax, JSON parsing, whitespace, and four public Codex CLI 0.144.0 schema canaries passed. The optional exhaustive repository run exceeded 300 seconds without emitting a failure and is not counted as passed. |
| Consent-duration/recovery correction | Complete and independently reviewed | Versioned-schema manifest `consent_7857c66fd76b25a58a6b4713` validated 59/94 windows with zero job errors, then the 15-minute grant expired before reservation 60 and left 35 pending; source/archive/authority unchanged. Product boundary and summary manifests now last one hour; mid-run expiry returns durable `consent_expired`; stage-generic recovery reconciles newly completed exact jobs, usage, and uncheckpointed reservations with per-manifest checkpoints across repeated rotation. Escaped boundary/summary and legacy-marker regressions prove no double count and only remaining submits. Independent re-review passed with no P0-P2. 190 M15 passed/2 expected opt-in skips, Ruff, strict mypy over 114 files, and whitespace pass. |
| Live boundaries | Resume required after duration correction | First run: 94 calls, zero validated, 93 `output_schema_rejected`, one `provider_unavailable`. Versioned retry: 59 calls/validated, 35 pending, zero job errors before consent expiry. Fresh exact resume manifest under standing authorization must replay/cache the 59 successes and submit only the remainder; private artifacts are under `output/m15-1-live-acceptance-20260721-121205/` and `output/m15-1-live-acceptance-20260721-125206/`. |
| Live summaries | Pending separate explicit consent | Frozen-membership summary preview/manifest must be presented after boundaries freeze |
| Final reviewer and private comparison | Pending | Source-first result must freeze before comparison with private oracle/mockups |
| Real Chrome and user visual approval | Pending | Actual final-head 100%/200% screenshots must be approved by the user |
| Final Release and exact PR head | Pending | Run once after visual approval; PR must remain open and unmerged |

## Rejected historical evidence

- The provider-free result contained no qualifying live boundary or summary jobs/cache/provenance.
- Its wide station/canvas presentation and technical labels failed the revised normal-flow,
  density, narrative-language, local-choice, and responsive acceptance requirements.
- Its prior reviews did not perform the required source-first then private-reference comparison of
  the same frozen candidate.
- Its screenshots and sanitized visible-order export remain local/committed historical artifacts
  only; they are not M15.1 acceptance evidence.

## Current limitations

- Corrected implementation is integrated locally but has not been pushed; the existing PR remains
  intentionally behind until live semantic, review, screenshot, Release, and final-head gates pass.
- The first M15.1 live boundary run consumed its consent without freezing membership. Its manifest
  cannot be reused; the corrected candidate requires a fresh exact preview before any retry.
- Full-game semantic quality, M14 dynamic adapters, runtime tracing, game/creator execution,
  installer/public distribution, and PR merge remain outside this correction.
- The visible task surface can set model and reasoning but exposes no fast-mode selector; that
  setting must remain unavailable/unverified for task dispatch.

This report must be updated with commands, exact heads, artifacts, reviews, live accounting,
immutability proof, user approval, Release results, and exact GitHub checks as M15.1 progresses.
