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
| Consent-duration/recovery correction | Coordinator plus independent reviewer | Versioned-schema live retry | Complete | Exact manifest `consent_7857c66fd76b25a58a6b4713` validated 59 windows with zero job errors, then expired before reservation 60 and left 35 pending. Source, archive, and M10-M13 authority rows stayed unchanged. Product grants are now one hour; mid-run expiry becomes durable `consent_expired`; stage-generic recovery reconciles newly completed jobs, usage, and uncheckpointed reservations via per-manifest checkpoints. Escaped boundary/summary and legacy-marker tests prove repeated rotation does not double count and only remaining jobs submit. Independent re-review passed with no P0-P2. 190 M15 passed/2 expected opt-in skips, Ruff, strict mypy over 114 files, and whitespace pass. |
| Live boundary stage | Coordinator | Reviewed corrections and fresh exact standing authorization | Resume required | First run: 94 calls, zero validated, 93 `output_schema_rejected`, one `provider_unavailable`. Versioned retry: 59 validated, 35 pending, zero job errors before 15-minute expiry. After duration-correction review/commit, generate a fresh exact manifest on the same isolated project and prove 59 cache/replay hits plus submission only for remaining jobs. User standing authorization applies to future M15.1 manifests in this task. |
| Live summary stage | Coordinator | Frozen membership and separate exact user consent | Pending | Present exact zero-submit summary manifest; run only after explicit summary consent; validate one-to-one summaries and atomically publish |
| Final source-first then oracle review | Separate visible Codex reviewer task | Frozen live candidate | Pending | Reviewer freezes blind source/evidence/screenshots result, then compares same hashes to private references; no unresolved P0-P2 |
| Real-browser and user visual acceptance | Coordinator | Reviewed final-head candidate | Pending | Required 100%/200% captures, layout/evidence assertions, and explicit user approval of actual screenshots |
| Final Release and PR readiness | Coordinator | User visual approval | Pending | One final Windows Release/package gate, lifecycle/evidence reconciliation, private-content scan, push exact passing head, PR #26 checks; leave unmerged |

Historical note: the original M15 tracks and reviews completed against the coarse provider-free
design, but the user rejected that semantic outcome. Their heads and artifacts remain history only
and do not satisfy any M15.1 row above.

All new visible tasks must use `gpt-5.6-sol` with High reasoning under current repository policy.
The task surface has no fast-mode selector, so record fast mode unavailable/unverified. Every
handoff must include exact base/head, branch/worktree, changed files, commands/results, assumptions,
limitations, likely conflicts, reviewer findings, and remaining acceptance work.
