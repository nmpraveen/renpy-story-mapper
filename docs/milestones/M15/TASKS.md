# M15.1 Phase 03 task ledger

Baseline: `e81523fe2cc42f1bc3d8dcb1a839bfd28876dfe9`

Integration branch: `codex/m15-phase03-story-browser`

Lifecycle: `In progress`

| Task | Owner | Scope / affected area | Dependencies | Status | Evidence / handoff |
|---|---|---|---|---|---|
| Preflight | Phase 03 Coordinator | Git baseline, V2 package/tests, private accepted-core package, protected fingerprints | User starts handoff | Complete | Local/remote `main` match `e81523f`; tracked diff clean; accepted core 1/1, 12 events, four choices, eight outcomes, zero failures; source/archive/project hash, size, and mtime match |
| Lock contract and shared design | Phase 03 Coordinator | `GOAL.md`, `PHASE_03_DESIGN.md`, lifecycle records | Preflight | Complete | One Phase 03 done condition, 18 criteria, exclusions, provider ceiling, shared records/endpoints, ownership, and evidence plan |
| Semantic review | Phase 03 Coordinator | Requirements, architecture, expected files/checks, evidence map | Locked contract/design | Complete | `SEMANTIC_REVIEW.md`: `PASS` before product edits |
| Native Phase 03 goal | Phase 03 Coordinator | Goal service and project-state pointer | Locked observable done condition | Complete | Active goal/task `019f9c53-6ef8-7a00-9ec0-f06c5e9dcdb0` exactly matches the contract done condition and remains active through PR readiness |
| Track A - synthesis/storage/API | Visible task `019f9c58-e638-71a0-b6a2-cb88b72f3d24`; worktree `C:/Users/prave/.codex/worktrees/e7ca/Renpy` | Versioned synthesis, validation/fallback, minimal core/synthesis storage, read-only base API, generalized tests | Goal active; semantic `PASS`; design freeze `4f6e3a6` | Complete | Final worker head `2319092`; sterile Terra adapter, schema binding, synthesis-only fallback, exact durable provenance, projection/storage/API complete; integrated byte-equivalently through `50bdc08` |
| Track A independent review | Visible task `019f9c67-af1c-7812-a471-1f6a98572f1c`; worktree `C:/Users/prave/.codex/worktrees/8255/Renpy` | Track A exact head and contract/exclusions | Track A frozen head | Complete | Initial P1/P3 findings at `420dbb7`, schema-file P2 at `62a0234`; final exact-head `PASS` at `2319092` with P0=P1=P2=P3=0; 50 focused, 210 V2/import, 82 storage/web/M10-M12 plus static gates |
| Track B - compact vertical browser | Visible task `019f9c8d-cfb6-7b32-8c7f-51482bbe39c6`; worktree `C:/Users/prave/.codex/worktrees/9ea6/Renpy` | Story Map V2 normal-flow page, responsive local branches, selection/context, generalized browser tests | Exact frozen checkpoint `4827b06` plus additive continuation seam | Complete | Corrected clean head `81313d7b2b86bf12c3236659f259c24f129dd00c`; final gate 10 focused/three-profile Chrome, exact 131 pass/2 opt-in skip adjacent, adversarial contracts, 107-file mypy, Ruff/JS/fixture/asset/diff; rereview pending |
| Track B independent review | Visible task `019f9ca9-ab9e-77c0-a2f1-0426f9472084`; worktree `C:/Users/prave/.codex/worktrees/4f7b/Renpy` | Track B exact head, responsive/accessibility/browser contract and exclusions | Track B frozen head | In progress | Rejected `2069eab` at P0=0/P1=0/P2=5/P3=0; same reviewer now rereviews exact corrected head `81313d7`, including fresh three-profile Chrome |
| Track C - path/detail navigation | Visible task `019f9c8d-cfa8-76c1-9111-7600e1180d35`; worktree `C:/Users/prave/.codex/worktrees/ee40/Renpy` | Anchor-to-M12 target binding, honest witness projection, detail/source navigation, generalized tests | Exact frozen checkpoint `4827b06` plus additive continuation seam | Complete | Corrected clean head `fb0f2ecd207848248e674f9c76af7a3d505019fb`; final gate 22 focused, 7 targeted HTTP/import/topology, 192 adjacent, Ruff, strict mypy, JSON/blob/diff/privacy; same-reviewer rereview pending |
| Track C independent review | Visible task `019f9ca6-cb8b-7503-afc0-9e4c51cd0946`; worktree `C:/Users/prave/.codex/worktrees/6915/Renpy` | Track C exact head, route/evidence correctness and exclusions | Track C frozen head | Complete | Exact corrected head `fb0f2ecd207848248e674f9c76af7a3d505019fb`: `PASS`, P0=P1=P2=P3=0; 22 focused, 7 finding-specific, 192 bounded, 3 architecture, 16 loopback plus static gates |
| Integration and provider-free verification | Phase 03 Coordinator | Reviewed track commits, focused/regression/static/privacy gates | All track reviews pass | Pending | Record exact integrated head and observed command results |
| Zero-submit preview and one Terra call | Phase 03 Coordinator | Private accepted core, exact synthesis payload/settings/accounting | Provider-free gates pass | Pending | One-call ceiling; no retry/substitution |
| Private browser/path acceptance | Phase 03 Coordinator | Exact private core/result, five target classes, reopen, 100%/200%, no remote requests | Integrated result stored | Pending | Outside-Git report and screenshots |
| User screenshot approval | User in Coordinator task | Actual final reviewed-head 100%/200% screenshots | Candidate screenshots captured | Pending | Explicit approval required |
| Final cross-track review | Separate visible read-only task/worktree | Exact integrated head, private result summary, screenshots, acceptance and exclusions | Final candidate frozen | Pending | No unresolved P0-P2 required |
| PR readiness | Phase 03 Coordinator | Evidence, completion report, push, PR, exact-head GitHub checks | User visual approval and final review pass | Pending | One open unmerged Phase 03 PR |

Every visible task must explicitly request `gpt-5.6-sol` with High reasoning. The available task
creation API has no fast-mode field, so fast mode is recorded as unavailable and unverified for
task dispatch rather than claimed disabled. This limitation does not relax the exact live synthesis
requirement, whose provider identity must independently verify Terra/High/fast-off.

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`. Record why a task is
blocked and what unblocks it.
