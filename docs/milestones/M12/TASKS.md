# M12 task ledger

Baseline: `fa8c543f648e085403f7448ab5e89f9b6e6c4fb6`

Integration branch: `codex/m12-route-solving`

Orchestration limitation: the current task/worker controls do not expose or verify model,
reasoning-effort, or fast-mode selectors. The required `gpt-5.6-sol` / high / fast-disabled
settings cannot be asserted from this surface. This is not an M12 product defect and must not
create product code or tests.

| Task | Owner | Scope / affected area | Dependencies | Status | Evidence / handoff |
|---|---|---|---|---|---|
| Contract and native goal | Primary | Contract, lifecycle pointer, exact goal | Approved scope | Complete | `GOAL.md`; active native goal `019f66ba-d396-7192-a445-a7277e84edf5`; `PROJECT_STATE.md` |
| Semantic review | Primary | Authority, entry/destination/state feasibility, architecture, tests, evidence | Contract recorded | Complete | `SEMANTIC_REVIEW.md`: `PASS` on 2026-07-15 |
| Core model and solver | Worker A | New M12 model/solver modules and focused tests | Semantic review `PASS`; literal base commit | Pending | Exact commit/check handoff required |
| Fixtures and acceptance contracts | Worker B | M12 synthetic fixtures and acceptance contracts | Semantic review `PASS`; literal base commit | Pending | Exact commit/check handoff required |
| Persistence and cache | Worker A or successor | M12 persistence/migration, cancellation, failure isolation, tests | Core interfaces integrated | Pending | Exact commit/check handoff required |
| API, side-panel UI, and export | Worker B or successor | M12 web API/contracts/static UI/export and tests | Core/persistence integrated | Pending | Exact commit/check handoff required |
| Integration and verification | Primary | Integrated diff, cross-module wiring, regression, acceptance, review | Worker handoffs | Pending | `VALIDATION_REPORT.md` |
| Private acceptance and completion artifacts | Primary | Bounded private run, reports, infographic, final review | Release checks passed | Pending | `COMPLETION_REPORT.md`, `INFOGRAPHIC.png` |
| PR readiness | Primary | Evidence audit, goal completion, lifecycle `PR ready`, one M12 PR | All acceptance complete | Pending | PR URL and exact head |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`. Record why a task is
blocked and what unblocks it.
