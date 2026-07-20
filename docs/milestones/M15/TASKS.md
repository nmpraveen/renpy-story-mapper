# M15 task ledger

Baseline: `a447a4eefbd7c093bdb2767e62a393805af068ac`

Integration branch: `codex/m15-msday1-narrative-map`

Phase Coordinator: current user-visible Codex task. This task's model, reasoning, and fast-mode
settings are not exposed to the coordinator and therefore remain unavailable/unverified; no claim
is made that repository prose changed them.

| Task | Owner | Scope / affected area | Dependencies | Status | Evidence / handoff |
|---|---|---|---|---|---|
| Contract and baseline | Phase Coordinator | M15 contract, lifecycle pointer, baseline/fixture hashes and current M11 metrics | User approval | Complete | Baseline `a447a4e`; tracked tree clean; source SHA-256/M11 metrics and 100%/200% screenshots under `output/playwright/m15-baseline/`; native goal `019f8014-e8f9-7af3-a54f-8cc3a7e7149c` active |
| Semantic review | Phase Coordinator | Requirements, architecture, frozen files/tests/evidence, single early gate | Approved scope and repository discovery | Complete | `SEMANTIC_REVIEW.md`: `PASS` on 2026-07-20 |
| Shared contracts and failing-first fixtures | Phase Coordinator | Versioned schemas/interfaces, synthetic/golden tests, retirement guards | Semantic review `PASS` | Complete | Frozen exact head `1ec0664ed6834b79cd1581a3edec7e16225bfc6f`; contract tests 7 passed; Ruff and strict mypy passed; intentional implementation gate 10 failed/1 passed before track work |
| Track A - deterministic corridors and event assembly | Task `019f8042-8627-7780-a515-355056881714`; worktree `C:/Users/prave/.codex/worktrees/8630/Renpy` | New Narrative Map domain, M10/M11 adapters, membership, quotient topology, provenance tests | Frozen shared contracts | In progress | Resumed from clean head `aa570f3ea7e6cba200cb2585f2f97386128cb07a`; correction/rereview cycles authorized through independent `PASS`, including same-edge descending hard-boundary rejection and full corridor-to-event-to-map acceptance proof |
| Track A independent review | Independent reviewer(s) inside Track A task | Read-only exact-head deterministic/topology/provenance review | Current Track A correction candidate | Pending | Every correction candidate requires an independent exact-head rereview; continue authorized cycles until `PASS` before integration |
| Track B - AI boundary and event-summary workflow | Task `019f8042-8632-7512-a2e3-42ac6932e558`; worktree `C:/Users/prave/.codex/worktrees/c6d6/Renpy` | Versioned prompts/schemas, ordered projection, persistence/resume/validation/repair/fake-provider tests | Frozen shared contracts; may compile alongside A | In progress | Resumed from clean head `6702e933dba82d19da8ea59ae246020eaebc9e80`; correction/rereview cycles authorized through independent `PASS`, including consent-bound request/accounting enforcement and claim-level repair preservation |
| Track B independent review | Independent reviewer(s) inside Track B task | Read-only exact-head provider/privacy/resume/validation review | Current Track B correction candidate | Pending | Every correction candidate requires an independent exact-head rereview; continue authorized cycles until `PASS` before integration |
| Track C - Story Map browser and legacy retirement | Separate user-visible task/worktree; ID pending | Narrative Map API/presentation/browser, layout, M12/M07/M08 visible retirement, compatibility, package/browser tests | Integrated reviewed Track A then Track B contracts | Pending | Explicit `gpt-5.6-sol`, High; fast-mode selector unavailable/unverified |
| Track C independent review | Independent worker inside Track C task | Read-only exact-head UI/API/compatibility/browser review | Track C candidate | Pending | Verdict and bounded correction loop required |
| Integration and verification | Phase Coordinator | Ordered integration, actual diff inspection, cross-track checks, private provider-free/browser/Windows acceptance | Reviewed A/B/C handoffs | Pending | No track candidate integrated; wait for independent A/B `PASS` verdicts before ordered integration |
| Final cross-track review | Separate read-only reviewer task | Exact integrated head, no edits | Frozen candidate and completed required checks | Pending | No unresolved P0-P2 correctness/security/narrative finding |
| Optional live Day 1 acceptance | Phase Coordinator only after fresh explicit consent | Exact manifest, bounded provider run, comparison, zero-call replay | Provider-free integration accepted; separate user consent | Pending | Optional; not authorized by milestone-start approval |
| PR readiness | Phase Coordinator | Completion report, infographic, evidence audit, branch push, one unmerged PR | Verification and reviews pass | Pending | PR URL/state and genuine readiness required |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`. Every worker handoff
must include base, exact head, branch/worktree, changed files, checks/results, assumptions, known
defects, conflicts, and remaining acceptance.
