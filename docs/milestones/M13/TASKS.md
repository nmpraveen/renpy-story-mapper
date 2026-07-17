# M13 task ledger

Baseline: `f67df8a7cb805bf4adf8590585bae700d2f3117f`

Integration branch: `codex/m13-narrative-layer`

Orchestration limitation: the available collaboration controls do not expose or verify model,
reasoning-effort, or fast-mode selectors. The repository dispatch policy cannot be asserted
through that surface. This must not create fixed provider settings in M13 product contracts or
tests and will be recorded in each delegated handoff if delegation is used.

| Task | Owner | Scope / affected area | Dependencies | Status | Evidence / handoff |
|---|---|---|---|---|---|
| Contract and native goal | Primary | `GOAL.md`, lifecycle pointer, exact native goal | Approved recovery scope | In progress | Existing task/goal `019f6ce8-55e7-76a2-9f64-202d00ebb9a5` resumed in this same task by explicit user approval; no second goal created; not complete |
| Semantic review | Primary | Requirements, architecture, expected files/tests/evidence | Contract recorded | Complete | `SEMANTIC_REVIEW.md`: `PASS` on 2026-07-16 |
| Contracts and evidence handles | Primary | M13 immutable contracts, claim DAG, handles, prompt schemas/templates, focused tests | Semantic review `PASS` | Complete | `7880b48`, `066bb42`, `86fa76a`, `859328e`; exact E/C handle, cache, claim, M12, and contradiction tests |
| Scene jobs and partial salvage | Primary | Independent scene projection, claim validation/repair/salvage, tests | Contracts | Complete | `2fa0a60`, `8d8a354`, `859328e`; claim-local salvage, deterministic title fallback, zero/one repair seam |
| Queue, cache, cancellation, batching | Primary | Durable state, retries, batches, budgets, consent, provider interface | Scene contracts | Complete | `1104293`, `8d8a354`, `2a41771`; independent item commit/retry/split, cancellation durability, exact replay |
| Segment hierarchy and summaries | Primary | Deterministic segments, chapters/routes/endings/plot, contradictions, tests | Durable scene artifacts | Complete | `70161fd`, `bd49168`, `1be9a88`, `a5d9c5f`; bounded fan-in at every level and route-aware plot |
| Browser narrative workflow | Primary | Local API, Narrative toggle, citation DAG, coverage/job drawer, browser tests | Summary services | Complete | `c01a169`, `32ed808`, `a5d9c5f`, `3193d50`; real Chrome 100%/200% pass |
| Privacy, scale, and private acceptance | Primary | Full-corpus simulation, bounded live/private harness, immutability | Integrated product | In progress | Historical provider-free pass at `e0fd3bf`; new provider-free/browser evidence is pending at `edf80ed`; any canary/live transmission remains separately gated |
| Character interpretation | Primary | Bounded participation/roles/route-aware arcs | Core hierarchy complete | Complete | `81fcacb`, `a5d9c5f`; common and route-specific roles remain separate and evidence-bound |
| Optional boundary/local/export work | Primary | Only if core gates are already complete | Release-critical work complete | Complete | Intentionally deferred as non-blocking: no weak-boundary overlay, LM Studio adapter, or export polish |
| Integration and verification | Primary | Integrate recovery A then B; inspect diffs; combined focused checks; freeze runtime; then gated acceptance | Recovery workers complete | In progress | Runtime frozen at `edf80ed`; combined 155 tests, targeted Ruff, and strict mypy passed; full Release passed every runtime/build gate with 1,005 tests except one evidence-only lifecycle-line mismatch now normalized without runtime changes |
| Corrective rereview | External Codex reviewer | Read-only review of `04082c0..9889035`; no full suite | Release-validated correction | Complete | Task/session `019f6d01-2c81-71c0-b459-d2a99ccc5be7`; `gpt-5.6-sol`/High/no-fast/read-only; verdict FAIL with two P1s; exact report/hash in `CORRECTIVE_REREVIEW_REPORT.md` |
| Browser acceptance and preview worker | Task `019f6d0f-b146-7f12-9294-3af8f7bc0bc7` | One Chrome 100%/200% run and one zero-submit preview; no tracked edits | Runtime freeze `e0fd3bf` | Complete | Browser report `dd873f0f...1437`; preview `406ee106...fb6`; verified handoff integrated without duplicate execution |
| Final evidence-gap audit worker | Task `019f6d0f-bd2a-7f11-9641-8e8a62db8935` | Read-only criterion/staleness audit; no tests or edits | Runtime freeze `e0fd3bf` | Complete | Identified stale heads/counts, missing rereview disposition, and final reconciliation checklist; superseded run-state observations were rechecked by Primary |
| Narrow recovery A: consent/settings | Task `019f6d5a-b372-71d2-a5a4-956e4654d8bc` | Stable consent identity, grant invariant, provider-settings plumbing, live-harness settings; worktree `C:\Users\prave\.codex\worktrees\ff39\Renpy` | Exact base `4e2bf7a` | Complete | Clean handoff `902d400` integrated as `cb17b55`; 28 focused tests plus Ruff/mypy/whitespace passed; read-only audit disposition verified; task API exposes no fast-mode selector, so fast state is not claimed verified |
| Narrow recovery B: schema/provider/fail-fast | Task `019f6d5a-b33b-7aa0-b64b-56bd73ce580c` | Schema v3, settings adapter, sanitized failures, circuit breaker, non-executed canary utility; worktree `C:\Users\prave\.codex\worktrees\97ee\Renpy` | Exact base `4e2bf7a` | Complete | Clean handoff `052b850` integrated as `edf80ed`; 106 focused tests plus Ruff/strict mypy/schema/whitespace passed; read-only audit disposition verified; no remote canary call; task API exposes no fast-mode selector, so fast state is not claimed verified |
| PR readiness | Primary | Evidence audit, reports, infographic, PR preparation | Verification and review passed | Blocked | Independent final-head PASS is absent; live acceptance failed; consent ID changes after grant; PR must not be created without approval |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`. Record why a task is
blocked and what unblocks it.
