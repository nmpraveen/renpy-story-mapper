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
| Track A - deterministic corridors and event assembly | Task `019f8042-8627-7780-a515-355056881714`; worktree `C:/Users/prave/.codex/worktrees/8630/Renpy` | New Narrative Map domain, M10/M11 adapters, membership, quotient topology, provenance tests | Frozen shared contracts | Complete | Clean exact head `6a28002f9f9165c70733eae5433537feebaa61a7`; 27 focused/contract/portable tests and 37 adjacent M10/M11 tests passed; all nine synthetic cases and immutable exact acceptance passed; coordinator diff audit clean |
| Track A independent review | `/root/track_a_exact_head_review` inside Track A task | Read-only exact-head deterministic/topology/provenance review | Current Track A correction candidate | Complete | Exact-head rereview at `6a28002f`: `PASS`, no P0-P2; reviewer made no edits or private-fixture access |
| Track B - AI boundary and event-summary workflow | Task `019f8042-8632-7512-a2e3-42ac6932e558`; worktree `C:/Users/prave/.codex/worktrees/c6d6/Renpy` | Versioned prompts/schemas, ordered projection, persistence/resume/validation/repair/fake-provider tests | Frozen shared contracts; may compile alongside A | Complete | Clean exact head `47fa6f48f3bf01e8ed91608407296d34210cf92c`; 46 focused/frozen and 157 adjacent M13 tests passed; Ruff, strict mypy, dependency/frozen-resource/diff checks passed; zero live/provider/private access |
| Track B independent review | `/root/m15_track_b_review` inside Track B task | Read-only exact-head provider/privacy/resume/validation review | Current Track B correction candidate | Complete | Final exact-head rereview at `47fa6f48`: `PASS`, no P0-P2; 196 expanded tests and focused claim-lock probes passed; reviewer made no edits |
| Track C - Story Map browser and legacy retirement | Task `019f80a7-5e33-7e81-8a4c-1aa7749d51bc`; worktree `C:/Users/prave/.codex/worktrees/fb82/Renpy` | Narrative Map API/presentation/browser, layout, M12/M07/M08 visible retirement, compatibility, package/browser tests | Integrated reviewed Track A then Track B contracts | In progress | Dispatched from exact integrated base `07e9ecd1635b8963cf36bb2c98248a5f703c5718` with `gpt-5.6-sol` High; fast-mode selector unavailable/unverified; correction/rereview cycles authorized through independent `PASS` |
| Track C independent review | Independent worker inside Track C task | Read-only exact-head UI/API/compatibility/browser review | Track C candidate | Pending | Verdict and bounded correction loop required |
| Integration and verification | Phase Coordinator | Ordered integration, actual diff inspection, cross-track checks, private provider-free/browser/Windows acceptance | Reviewed A/B/C handoffs | In progress | Reviewed A then B integrated through coordinator head `9c0f5d878b32ce4f91b4257f357ca42871d0b49e`; expected shared-export conflict preserved both APIs; 66 focused M15, 69 adjacent M10/M11, and 157 adjacent M13 tests plus Ruff, mypy, pip, and diff checks passed; Track C and final acceptance pending |
| Final cross-track review | Separate read-only reviewer task | Exact integrated head, no edits | Frozen candidate and completed required checks | Pending | No unresolved P0-P2 correctness/security/narrative finding |
| Optional live Day 1 acceptance | Phase Coordinator only after fresh explicit consent | Exact manifest, bounded provider run, comparison, zero-call replay | Provider-free integration accepted; separate user consent | Pending | Optional; not authorized by milestone-start approval |
| PR readiness | Phase Coordinator | Completion report, infographic, evidence audit, branch push, one unmerged PR | Verification and reviews pass | Pending | PR URL/state and genuine readiness required |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`. Every worker handoff
must include base, exact head, branch/worktree, changed files, checks/results, assumptions, known
defects, conflicts, and remaining acceptance.
