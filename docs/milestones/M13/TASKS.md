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
| Contracts and evidence handles | Primary | M13 immutable contracts, claim DAG, handles, prompt schemas/templates, focused tests | Semantic review `PASS` | Complete | `7880b48`, `066bb42`, `86fa76a`, `859328e`; exact E/C handle, cache, claim, M12, and contradiction tests |
| Scene jobs and partial salvage | Primary | Independent scene projection, claim validation/repair/salvage, tests | Contracts | Complete | `2fa0a60`, `8d8a354`, `859328e`; claim-local salvage, deterministic title fallback, zero/one repair seam |
| Queue, cache, cancellation, batching | Primary | Durable state, retries, batches, budgets, consent, provider interface | Scene contracts | Complete | `1104293`, `8d8a354`, `2a41771`; independent item commit/retry/split, cancellation durability, exact replay |
| Segment hierarchy and summaries | Primary | Deterministic segments, chapters/routes/endings/plot, contradictions, tests | Durable scene artifacts | Complete | `70161fd`, `bd49168`, `1be9a88`, `a5d9c5f`; bounded fan-in at every level and route-aware plot |
| Browser narrative workflow | Primary | Local API, Narrative toggle, citation DAG, coverage/job drawer, browser tests | Summary services | Complete | `c01a169`, `32ed808`, `a5d9c5f`, `3193d50`; real Chrome 100%/200% pass |
| Privacy, scale, and private acceptance | Primary | Full-corpus simulation, bounded live/private harness, immutability | Integrated product | In progress | Provider-free complete private corpus pass; exact live manifest prepared with zero submissions and awaiting consent |
| Character interpretation | Primary | Bounded participation/roles/route-aware arcs | Core hierarchy complete | Complete | `81fcacb`, `a5d9c5f`; common and route-specific roles remain separate and evidence-bound |
| Optional boundary/local/export work | Primary | Only if core gates are already complete | Release-critical work complete | Complete | Intentionally deferred as non-blocking: no weak-boundary overlay, LM Studio adapter, or export polish |
| Integration and verification | Primary | Integrated diff, Windows suites, browser/package/private acceptance | Implementation complete | In progress | Product head `859328e`; Release 951 passed/7 deselected; provider-free private and Chrome pass; live/independent gates remain |
| Independent review | Pending assignment | Read-only contract/security/correctness/acceptance review | Verified integration head | Pending | No P0/P1 required |
| PR readiness | Primary | Evidence audit, reports, infographic, PR preparation | Verification and review passed | Pending | Live consented acceptance, independent review, infographic, and final evidence audit remain; PR must not be created without approval |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`. Record why a task is
blocked and what unblocks it.
