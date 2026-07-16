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
| Core model and solver | Worker `m12_core_solver` | `m12_model.py`, `m12_solver.py`, focused tests | Literal base `f2946e00baa6dc83577773d66544ed6cd47b0218` | Complete | Branch `codex/m12-core`; worktree `C:\Users\prave\Documents\Codex\Renpy-m12-core`; result `518330afce56ccdc65103bb061fd77be19514ecc`; integrated as `c0dc1f2224356a6ee38b5698f3d4fb7a094b0c94`; no worker PR |
| Persistence and cache | Worker `m12_persistence` | M12 persistence, exact cache identity, cancellation/failure isolation, tests | Literal base `f2946e00baa6dc83577773d66544ed6cd47b0218` | Complete | Branch `codex/m12-persistence`; worktree `C:\Users\prave\Documents\Codex\Renpy-m12-persistence`; result `f82b274d18eb6c156196d38ac8bf3afd46bcbe99`; integrated as `64603fa975e4d65a388402199f15872bb79d0af3`; no worker PR |
| Side-panel UI | Worker `m12_ui` | Existing browser Route Map panel, deterministic rendering/export, UI tests | Literal base `64603fa975e4d65a388402199f15872bb79d0af3` | Complete | Branch `codex/m12-ui`; worktree `C:\Users\prave\Documents\Codex\Renpy-m12-ui`; result `cb33f19060e3171da1f0741d5af113b86e3f2938`; integrated as `5da3e95b1abb0e150fbf1ee5d42ae424f686f9b5`; no worker PR |
| Authority/API integration | Primary | Fixture, authority service, API workflow, call/return context, compact private-scale loader | Worker slices integrated | Complete | `814499a`, `44f2e68`, `ba0937e`, `a5606ea`, `3090f78`, `9bda6f3` |
| Browser and scale acceptance | Worker `m12_acceptance` | Real Chrome workflow and deterministic scale harness | Literal base `ba0937ecd38e814628cb22b58bb318bdbc1f8212` | Complete | Branch `codex/m12-acceptance`; worktree `C:\Users\prave\Documents\Codex\Renpy-m12-acceptance`; initial result `ad63d65d4e990903198233adc89690dbb7bd76f9`; final result `edb79c228112443c9fb51d4c28d263e22405044b`; acceptance integrated as `1779804` and paint wait as `01d39ee`; worker product-fix commit `01daf496417f4e5f129e8c10087f846fa5142ca3` was superseded by primary integration fix `a5606ea`; no worker PR |
| Assurance and private harness | Worker `m12_assurance` | Architecture, fault injection, private harness/tests | Literal base `ba0937ecd38e814628cb22b58bb318bdbc1f8212` | Complete | Branch `codex/m12-assurance`; worktree `C:\Users\prave\Documents\Codex\Renpy-m12-assurance`; result `2989522a912ea3dc531551a8d6ee56c209f2f61f`; integrated as `4da83f0b67fd2da222a1fe81b2f46ab33158a994`; no worker PR |
| Primary correctness corrections | Primary | Chronology, distinct entry ranking, cancellation publication, browser manifest | Integrated implementation and adversarial reviews | Complete | `ea52f92`, `5faa12a`, `69c1928`, `1df8309`; all findings retested and reviewed |
| Integration and verification | Primary | Integrated diff, cross-module wiring, regressions, browser/scale/private acceptance | All implementation handoffs | Complete | `VALIDATION_REPORT.md`; validated product head `1df83098872fb63d434ff3e59a79e0f286944260`; Fast 39, Focused 97+1 skip, Release 762+6 deselected |
| Final semantic review | Worker `m12_semantic_rereview` | Read-only solver/authority/contract review | Literal head `1df83098872fb63d434ff3e59a79e0f286944260` | Complete | `PASS`; targeted 11, full M12 97+1 skip, focused 88; Ruff/mypy/JS/manifest/diff passed; no edits or PR |
| Final delivery review | Worker `m12_final_delivery_review` | Read-only persistence/API/UI/security/acceptance review | Literal head `1df83098872fb63d434ff3e59a79e0f286944260` | Complete | `PASS`; targeted 8, package/manifest 15, repeated-scene probe; browser/scale inspected; no edits or PR |
| Private acceptance and completion artifacts | Primary | Bounded private run, reports, native infographic, final evidence | Final product head and Release checks | Complete | Five targets/three gated; external report SHA-256 `194551a06be474bfaec41f6e5f01a75c6d0240b02cfa6d28c296dc50791d892e`; `INFOGRAPHIC.png` SHA-256 `c7e651bec7fa9df2080d06649e4d71c8c205279bf63ea1d5c6b96f845a12f3f5` |
| Changes-requested contract reconciliation | Primary | Same M12 contract/branch/PR; lifecycle and four merge blockers | User review on literal base `a02151ebc45d2d05efc6d582a8757fbca87aa6d5` | Complete | Existing semantic `PASS` applies; no restart, second goal, branch, or PR |
| Supported constraint intersection | Primary / bounded worker | Boolean, literal, numeric supported constraints and contradiction facts | Changes-requested contract | Complete | 7 direct regressions plus exhaustive closed-world negative pass |
| Completed call-frame popping | Primary / bounded worker | Matching summary continuation, nested/shared/recursive/malformed call tests | Changes-requested contract | Complete | 40+ sequential calls, nesting, caller isolation, recursion, and malformed cases pass |
| Parent-pointer route prefixes | Primary | Bounded prefix store, accounting, reconstruction, scale tests | Constraint/call corrections integrated | Complete | 500/1,000/2,000 routes complete; accounting growth 1.998073/1.999035 |
| Conservative exact loop acceleration | Primary | Wire existing decision helper to M10 loop authority and projections | Prefix refactor integrated | Complete | Exact structural cycle, phase-aware intermediate exit, and grind 25 pass; unsafe loop cases stay conservative |
| Changes-requested validation and evidence | Primary | Focused, M12, Release, browser, persistence, fault, private, scale | All four corrections | Complete | Fast 39; Focused 123+1 skip; Release 788+6 deselected; browser/private/scale passed |
| Changes-requested final review | Worker `m12_final_delivery_review` | Read-only exact correction range and phase-soundness reproduction | Literal base `a02151ebc45d2d05efc6d582a8757fbca87aa6d5`; literal result `40c10fd9bb31e9303efeb302dacd081e1007911c` | Complete | Initial review found the intermediate-exit phase blocker; `40c10fd` fixed it; re-review `PASS`, 64 focused tests, Ruff, strict mypy, diff check |
| PR readiness | Primary | Evidence audit and push corrections to existing PR #22 | Final review requested by user | Complete | PR remains open and unmerged; corrected head is ready for final user review |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`. Record why a task is
blocked and what unblocks it.
