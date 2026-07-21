# M15.1 task ledger

Original baseline: `a447a4eefbd7c093bdb2767e62a393805af068ac`

Correction base: `55ae57406cfb07a3c088d0dfd7c3b7e04ca9a719`

Integration branch: `codex/m15-msday1-narrative-map`

Pull request: [PR #26](https://github.com/nmpraveen/renpy-story-mapper/pull/26), open and unmerged.

| Task | Owner | Dependencies | Status | Evidence / next gate |
|---|---|---|---|---|
| Correction preflight | Coordinator | User instruction | Complete | Exact local/remote head and PR #26 verified; source/archive fingerprints match; private paths remain ignored; unrelated untracked files preserved |
| Lifecycle correction and revised semantic gate | Coordinator | Complete plan and authority reading | Complete | Prior PR-ready result revoked; revised `GOAL.md`; `SEMANTIC_REVIEW.md` ends `PASS` on 2026-07-21 |
| Replacement native goal | Coordinator | Revised safe done condition and semantic `PASS` | Complete | Goal `019f8014-e8f9-7af3-a54f-8cc3a7e7149c` is active with the verbatim M15.1 done condition; the goal service reused the current coordinator task ID |
| Shared schemas, examples, and failing-first freeze | Coordinator | Active goal | Complete | Exact base `c768b19c8d9364db8f1987cb420e69ac0c2e535d`; 14 contract/workflow checks, Ruff, and strict mypy pass; expected Track A/B/C baseline is 7 failures |
| Track A - deterministic semantics | Task `019f84a1-897e-7a91-a622-fc00f5a10d72`; `C:/Users/prave/.codex/worktrees/dc1a/Renpy`; branch `codex/m15-1-track-a` | Shared frozen head | Complete | Reviewed head `09062370aacb074da28ff2cd3aeb603ea69197cf`; independent exact-head review passed with no unresolved P0-P2; eight commits integrated |
| Track B - two-stage semantic lifecycle | Task `019f84a1-897f-7953-a1f6-fa043410bcee`; `C:/Users/prave/.codex/worktrees/b547/Renpy`; branch `codex/m15-1-product-path-backend` | Shared frozen head plus integrated product path | Complete | Original reviewed head `5b7d9d184025f4957cbaa6b0fec3c4da2518c376`; provenance correction `6c41f0df`; final supported product-path correction `ca048973662d72844ece6f2c8237fca5ca67b4cd`; each exact head independently passed with no unresolved P0-P2 |
| Track C - compact Story Map product | Task `019f84a1-897b-7a40-ba52-1f26d6dca090`; `C:/Users/prave/.codex/worktrees/bb69/Renpy`; branch `codex/m15-1-track-c` | Shared frozen head | Complete | Original reviewed head `1f8e4a1`; final compatibility correction `61a3eef19ed0c8a020090a8f1bd5b51c9ad67596`; independent exact-head reviews passed with no unresolved P0-P2 |
| Ordered integration and fake-provider acceptance | Coordinator | Reviewed Tracks A/B/C | Complete | Integrated head `4f6f740`; coordinator verification: 174 M15 passed/2 expected opt-in skips, 169 web/M10/M11 compatibility passed, enabled Chrome 10 passed, Ruff, strict mypy over 114 source files, JavaScript syntax, whitespace, and private-reference diff scan passed |
| Provider-schema correction | Coordinator plus independent reviewer | Failed first live boundary run | Complete | Historical resources preserved; active response identities bumped to boundary/event v2 and semantic boundary/summary v3; all four current/stale routes and all eight delegated uniqueness sites have direct regression coverage. Independent re-review passed with no P0-P2. 184 M15 passed/2 expected opt-in skips, 169 compatibility passed, enabled Chrome 10 passed, Ruff, strict mypy over 114 files, JavaScript/JSON/whitespace checks and four public live schema canaries passed. Optional full-repository pytest exceeded 300 seconds without emitted failures and is not recorded as a pass. |
| Consent-duration/recovery correction | Coordinator plus independent reviewer | Versioned-schema live retry | Complete | Exact manifest `consent_7857c66fd76b25a58a6b4713` validated 59 windows with zero job errors, then expired before reservation 60 and left 35 pending. Source, archive, and M10-M13 authority rows stayed unchanged. Product grants are now one hour; mid-run expiry becomes durable `consent_expired`; terminal-record fingerprints and exact ledger snapshots recover calls/usage once across repeated and cross-process rotation. Same-stage overlap is blocked through expiry plus timeout, rotated runners cancel before later reservations, and advanced phases cannot regress. Independent re-review passed with no P0-P2. 196 M15 passed/2 expected opt-in skips, Ruff, strict mypy over 114 files, and whitespace pass. |
| Live boundary stage | Coordinator | Reviewed corrections and standing authorization | Complete | Final checkpoint is 94/94 validated; manifest/result SHA-256 `817889a6…bc29` / `d448ed96…ca66`; frozen membership `049a327b…189b`; source/archive/authority unchanged. |
| Live summary stage | Coordinator | Frozen membership and standing authorization | Complete | Exact manifest `consent_710e992d5a0f47e3108351de` at `e925afd` completed 161/161 with no errors and published `139c690e…c8f`. Manifest/result SHA-256 `28f8612d…be30` / `557745d7…32c`; cumulative calls/reservations 529/529; source/archive/authority unchanged. Recovery/race/repair corrections independently passed with no P0-P2; 203 M15 passed/2 browser skips, Ruff, strict mypy 114. |
| Final source-first then oracle review | Separate visible Codex reviewer task | Frozen live candidate | Changes requested | Fresh uncontaminated Stage 1 froze `ac898b0` and failed with one P0, three P1, and one P2 before oracle/mockup access. Correct producer-lineage reading, compact story projection, chronological choice placement, factual summaries, and technical/generic promotion; then freeze a new blind Stage 1 before any Stage 2 comparison. |
| Real-browser and user visual acceptance | Coordinator | Reviewed final-head candidate | Pending | Required 100%/200% captures, layout/evidence assertions, and explicit user approval of actual screenshots |
| Final Release and PR readiness | Coordinator | User visual approval | Pending | One final Windows Release/package gate, lifecycle/evidence reconciliation, private-content scan, push exact passing head, PR #26 checks; leave unmerged |

Historical note: the original M15 tracks and reviews completed against the coarse provider-free
design, but the user rejected that semantic outcome. Their heads and artifacts remain history only
and do not satisfy any M15.1 row above.

All new visible tasks must use `gpt-5.6-sol` with High reasoning under current repository policy.
The task surface has no fast-mode selector, so record fast mode unavailable/unverified. Every
handoff must include exact base/head, branch/worktree, changed files, commands/results, assumptions,
limitations, likely conflicts, reviewer findings, and remaining acceptance work.
