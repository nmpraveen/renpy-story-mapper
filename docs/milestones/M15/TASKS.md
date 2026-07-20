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
| Track A - deterministic corridors and event assembly | Task `019f8042-8627-7780-a515-355056881714`; worktree `C:/Users/prave/.codex/worktrees/8630/Renpy` | New Narrative Map domain, M10/M11 adapters, membership, quotient topology, provenance tests | Frozen shared contracts | Blocked | Clean corrected head `aa570f3ea7e6cba200cb2585f2f97386128cb07a`; 27 Track A tests, 37 adjacent M10/M11 tests, Ruff, strict mypy, diff check, all nine synthetic cases, and exact private acceptance passed; rereview retains two P1s after the authorized correction cycle |
| Track A independent review | `/root/track_a_exact_head_review` inside Track A task | Read-only exact-head deterministic/topology/provenance review | Track A candidate | Complete | First review found five P1 areas; rereview `FAIL` at `aa570f3` with two P1s: reversed hard-boundary corridors can pass shared-edge validation, and acceptance still bypasses/infers parts of the full corridor-to-map pipeline |
| Track B - AI boundary and event-summary workflow | Task `019f8042-8632-7512-a2e3-42ac6932e558`; worktree `C:/Users/prave/.codex/worktrees/c6d6/Renpy` | Versioned prompts/schemas, ordered projection, persistence/resume/validation/repair/fake-provider tests | Frozen shared contracts; may compile alongside A | Blocked | Clean corrected head `6702e933dba82d19da8ea59ae246020eaebc9e80`; 24 focused/frozen tests, 135 adjacent M13 regressions, Ruff, strict mypy, dependency, and diff checks passed; rereview retains two P1s after the authorized correction cycle |
| Track B independent review | `/root/m15_track_b_review` inside Track B task | Read-only exact-head provider/privacy/resume/validation review | Track B candidate | Complete | First review found five issues; rereview `FAIL` at `6702e93` with two P1s: direct requests can exceed/reuse consent budgets, and summary repair can replace valid sibling claims |
| Track C - Story Map browser and legacy retirement | Separate user-visible task/worktree; ID pending | Narrative Map API/presentation/browser, layout, M12/M07/M08 visible retirement, compatibility, package/browser tests | Integrated reviewed Track A then Track B contracts | Pending | Explicit `gpt-5.6-sol`, High; fast-mode selector unavailable/unverified |
| Track C independent review | Independent worker inside Track C task | Read-only exact-head UI/API/compatibility/browser review | Track C candidate | Pending | Verdict and bounded correction loop required |
| Integration and verification | Phase Coordinator | Ordered integration, actual diff inspection, cross-track checks, private provider-free/browser/Windows acceptance | Reviewed A/B/C handoffs | Blocked | No track candidate integrated; renewed authority for narrowly bounded A/B corrections and rereviews is required before ordered integration |
| Final cross-track review | Separate read-only reviewer task | Exact integrated head, no edits | Frozen candidate and completed required checks | Pending | No unresolved P0-P2 correctness/security/narrative finding |
| Optional live Day 1 acceptance | Phase Coordinator only after fresh explicit consent | Exact manifest, bounded provider run, comparison, zero-call replay | Provider-free integration accepted; separate user consent | Pending | Optional; not authorized by milestone-start approval |
| PR readiness | Phase Coordinator | Completion report, infographic, evidence audit, branch push, one unmerged PR | Verification and reviews pass | Pending | PR URL/state and genuine readiness required |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`. Every worker handoff
must include base, exact head, branch/worktree, changed files, checks/results, assumptions, known
defects, conflicts, and remaining acceptance.
