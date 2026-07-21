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
| Track A - deterministic semantics | Task `019f84a1-897e-7a91-a622-fc00f5a10d72`; `C:/Users/prave/.codex/worktrees/dc1a/Renpy`; branch `codex/m15-1-track-a` | Shared frozen head | In progress | Started from exact `c768b19`; provider-independent fine units, candidates, deterministic hierarchy/topology, persistence helpers, fixtures, clean commit and independent exact-head review |
| Track B - two-stage semantic lifecycle | Task `019f84a1-897f-7953-a1f6-fa043410bcee`; `C:/Users/prave/.codex/worktrees/b547/Renpy`; branch `codex/m15-1-track-b-lifecycle` | Shared frozen head | In progress | Started from exact `c768b19`; boundary/summary projection, exact consents, durable jobs/cache/accounting, validation/publication/replay, clean commit and independent exact-head review |
| Track C - compact Story Map product | Task `019f84a1-897b-7a40-ba52-1f26d6dca090`; `C:/Users/prave/.codex/worktrees/bb69/Renpy`; branch `codex/m15-1-track-c` | Shared frozen head | In progress | Started from exact `c768b19`; frontend-design skill, production controls, normal-flow vertical HTML, local connectors, responsive evidence/browser coverage, clean commit and independent exact-head review |
| Ordered integration and fake-provider acceptance | Coordinator | Reviewed Tracks A/B/C | Pending | Inspect and integrate reviewed commits; focused semantic/API/browser/compatibility/privacy gates; freeze exact candidate |
| Live boundary stage | Coordinator | Integrated fake-provider candidate and exact user consent | Pending | Present exact zero-submit boundary manifest; run only after explicit boundary consent; validate one-to-one decisions and freeze membership |
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
