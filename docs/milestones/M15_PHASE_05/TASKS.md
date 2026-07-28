# M15.1 Phase 05 task ledger

Baseline: merged `main` at `268d30ed15d50136be5a88d464f79adaf7f32f9e`

| Task | Owner | Scope / affected area | Dependencies | Status | Evidence / handoff |
|---|---|---|---|---|---|
| Semantic review | One Sol/Ultra reviewer | Confirm the smallest useful outcome, seams, exclusions, and lean evidence | Approved scope | In progress | `SEMANTIC_REVIEW.md` |
| AI grouping and deterministic projection | Backend implementation thread | Reuse cached summaries; bounded grouping/synthesis; exact coverage/order validation; focused Python tests | Semantic review `PASS` | Pending | Thread/commit pending |
| Scrolling story timeline | Browser implementation thread | Existing reader composition; vertical groups, inline branches/rejoins/routes, meaningful path rail; focused browser tests | Frozen existing reader seam and semantic review `PASS` | Pending | Thread/commit pending |
| Real example and user review | Orchestra | Run the accepted MsDenvers map, capture current screenshots, pause for usefulness verdict | Integrated vertical path | Pending | Pending |
| Integration and verification | Orchestra plus one final Sol/Ultra reviewer | Integrate worker commits; focused gate; exact-head review | User accepts real result | Pending | Pending |
| PR readiness | Orchestra | Evidence, Release/package gate, push once, sharded CI, PR | Verification passed | Pending | Pending |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`.

The two implementation threads are the only concurrent broad workers. Worker settings are explicit
`gpt-5.6-sol` with Ultra reasoning; the thread API exposes no fast-mode selector, so fast mode is
unavailable/unverified.
