# M13 task ledger

Baseline: `f67df8a7cb805bf4adf8590585bae700d2f3117f`

Integration branch: `codex/m13-narrative-layer`

Orchestration limitation: the available collaboration controls do not expose or verify model,
reasoning-effort, or fast-mode selectors. The repository dispatch policy cannot be asserted
through that surface. This must not create fixed provider settings in M13 product contracts or
tests and will be recorded in each delegated handoff if delegation is used.

| Task | Owner | Scope / affected area | Dependencies | Status | Evidence / handoff |
|---|---|---|---|---|---|
| Contract and native goal | Primary | `GOAL.md`, lifecycle pointer, exact native goal | Approved scope | Complete | Active goal `019f6a76-1675-7ad3-bcbc-8741693751a3`; baseline/branch recorded |
| Semantic review | Primary | Requirements, architecture, expected files/tests/evidence | Contract recorded | Complete | `SEMANTIC_REVIEW.md`: `PASS` on 2026-07-16 |
| Contracts and evidence handles | Primary | M13 immutable contracts, claim DAG, handles, prompt schemas/templates, focused tests | Semantic review `PASS` | In progress | Semantic gate passed; implementation may begin |
| Scene jobs and partial salvage | Primary | Independent scene projection, claim validation/repair/salvage, tests | Contracts | Pending | Pending |
| Queue, cache, cancellation, batching | Primary | Durable state, retries, batches, budgets, consent, provider interface | Scene contracts | Pending | Pending |
| Segment hierarchy and summaries | Primary | Deterministic segments, chapters/routes/endings/plot, contradictions, tests | Durable scene artifacts | Pending | Pending |
| Browser narrative workflow | Primary | Local API, Narrative toggle, citation DAG, coverage/job drawer, browser tests | Summary services | Pending | Pending |
| Privacy, scale, and private acceptance | Primary | Full-corpus simulation, bounded live/private harness, immutability | Integrated product | Pending | Pending |
| Character interpretation | Primary | Bounded participation/roles/route-aware arcs | Core hierarchy complete | Pending | Pending |
| Optional boundary/local/export work | Primary | Only if core gates are already complete | Release-critical work complete | Pending | Non-blocking by contract |
| Integration and verification | Primary | Integrated diff, Windows suites, browser/package/private acceptance | Implementation complete | Pending | `VALIDATION_REPORT.md` |
| Independent review | Pending assignment | Read-only contract/security/correctness/acceptance review | Verified integration head | Pending | No P0/P1 required |
| PR readiness | Primary | Evidence audit, reports, infographic, PR preparation | Verification and review passed | Pending | PR must not be created without approval |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`. Record why a task is
blocked and what unblocks it.
