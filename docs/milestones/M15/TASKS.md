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
| Track A - deterministic corridors and event assembly | Task `019f8042-8627-7780-a515-355056881714`; worktree `C:/Users/prave/.codex/worktrees/8630/Renpy` | New Narrative Map domain, M10/M11 adapters, membership, quotient topology, provenance tests, amended leading-coverage correction | Amended shared contract | In progress | Integrated head `6a28002f` passed its earlier review; final integrated review later found setup/progression authority defects. M10-only progression fix is committed at Track A head `49b214b`; exact-bound coverage correction and rereview pending. |
| Track A independent review | Reviewers inside Track A task | Read-only exact-head deterministic/topology/provenance/correction review | Current Track A correction candidate | In progress | Review at `05c6a4d` found two P1s; M10-label authority is corrected at `49b214b`. Remaining setup ambiguity is addressed by the semantic amendment and requires a fresh PASS with no P0-P2. |
| Track B - AI boundary and event-summary workflow | Task `019f8042-8632-7512-a2e3-42ac6932e558`; worktree `C:/Users/prave/.codex/worktrees/c6d6/Renpy` | Versioned prompts/schemas, ordered projection, persistence/resume/validation/repair/fake-provider tests | Frozen shared contracts; may compile alongside A | Complete | Clean exact head `47fa6f48f3bf01e8ed91608407296d34210cf92c`; 46 focused/frozen and 157 adjacent M13 tests passed; Ruff, strict mypy, dependency/frozen-resource/diff checks passed; zero live/provider/private access |
| Track B independent review | `/root/m15_track_b_review` inside Track B task | Read-only exact-head provider/privacy/resume/validation review | Current Track B correction candidate | Complete | Final exact-head rereview at `47fa6f48`: `PASS`, no P0-P2; 196 expanded tests and focused claim-lock probes passed; reviewer made no edits |
| Track C - Story Map browser and legacy retirement | Task `019f80a7-5e33-7e81-8a4c-1aa7749d51bc`; worktree `C:/Users/prave/.codex/worktrees/fb82/Renpy` | Narrative Map API/presentation/browser, layout, M12/M07/M08 visible retirement, compatibility, package/browser tests | Integrated reviewed Track A then Track B contracts | Complete | Final clean head `47d7104ee527737f726f457a5ee4e2cbf3e05069`; initial delivery plus viewport-race and repeated-title search corrections; focused/adjacent, static/package, and 100%/200% Chrome gates pass; zero provider/private text |
| Track C independent review | `/root/track_c_exact_head_review` inside Track C task | Read-only exact-head UI/API/compatibility/browser review | Track C candidate | Complete | Fresh rereview at `47d7104`: `PASS`, no P0-P2; 245 focused/frozen/compatibility/security tests plus fresh Chrome and static gates; reviewer made no edits |
| Integration and verification | Phase Coordinator | Ordered integration, actual diff inspection, cross-track checks, private provider-free/browser/Windows acceptance | Reviewed A/B/C handoffs | In progress | A+B+C product integrated through `38c2ccb`; prior exact evidence is stale after the final-review findings. Amended correction integration, regenerated exact/browser evidence, and final Release remain pending. |
| Final cross-track review | Separate read-only reviewer task | Exact integrated head, no edits | Frozen candidate and completed required checks | Pending | No unresolved P0-P2 correctness/security/narrative finding |
| Optional live Day 1 acceptance | Phase Coordinator only after fresh explicit consent | Exact manifest, bounded provider run, comparison, zero-call replay | Provider-free integration accepted; separate user consent | Pending | Optional; not authorized by milestone-start approval |
| PR readiness | Phase Coordinator | Completion report, infographic, evidence audit, branch push, one unmerged PR | Verification and reviews pass | In progress | Native `INFOGRAPHIC.png` remains valid; stale `VISIBLE_ORDER.txt` must be regenerated after correction. Final Release/review, PR URL/state, and genuine readiness remain. |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`. Every worker handoff
must include base, exact head, branch/worktree, changed files, checks/results, assumptions, known
defects, conflicts, and remaining acceptance.
