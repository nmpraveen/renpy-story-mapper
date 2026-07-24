# M15.1 Phase 02 task ledger

Integration branch: `codex/m15-msday1-narrative-map`

Pull request: [PR #26](https://github.com/nmpraveen/renpy-story-mapper/pull/26), draft and
unmerged.

Lifecycle: `Semantic review`

| Task | Owner | Dependencies | Affected area | Status / evidence |
|---|---|---|---|---|
| Phase 02 preflight | Coordinator | User starts Phase 02 handoff | Read-only repo/PR/evidence | Complete: clean required worktree at `f914908`; branch 136 commits ahead of remote; PR #26 open/draft/unmerged at `bc9a38c`; Phase 01 package and recorded source/archive fingerprints present |
| Lock Phase 02 contract | Coordinator | Preflight | M15 lifecycle docs | Complete: one done condition, deliverables, 16 acceptance criteria, exclusions, evidence, provider ceilings, topology, and handoff rules recorded |
| Freeze simple V2 design | Coordinator | Contract | `PHASE_02_DESIGN.md` | Complete: new package boundary, lower-level authority, compact records, overlay, partial behavior, provider states, seams, and forbidden Stage H/E dependencies recorded |
| Create native Phase 02 goal | Coordinator | Locked contract | Goal service / project state | Complete: active goal/task `019f9676-c357-7803-a891-f03782bbb8ee` exactly matches the contract done condition |
| Early contract review | Visible read-only task `019f967d-8800-79e2-9dea-5f2412f6eecf` | Locked contract and design | Docs and read-only source discovery | `REVISE` at `df75532`: no P0/P2; four P1s in lifecycle reconciliation, branch-event lineage, concrete transport seam, and deliberate local-only state. One bounded correction is prepared; same-task rereview pending. Broad implementation remains paused. |
| Shared contracts and failing-first tests | Coordinator | Early reviewer `PASS` | `story_map_v2` seams/tests | Pending |
| Track A implementation and exact-head review | Separate visible Track A coordinator | Shared freeze | Provider-neutral V2 core | Pending |
| Track B implementation and exact-head review | Separate visible Track B coordinator | Shared freeze | Execution/fallback policy | Pending |
| Integration and provider-free verification | Coordinator | Reviewed Track A/B commits | Integrated package/tests | Pending |
| Private Day 1 acceptance | Coordinator | Provider-free integration pass | Outside-Git acceptance artifacts | Pending |
| Final exact-head review | Separate visible read-only reviewer | Frozen integration head/artifacts | Full Phase 02 contract | Pending |
| Lifecycle, commit, PR checkpoint | Coordinator | Final review pass | Docs/Git/PR #26 | Pending; PR must remain draft/unmerged |

Historical Stage H/E, adjacent-gap, atom/hierarchy, Phase 01, and prior review tasks remain readable
in Git history and earlier M15 evidence. They are not active Phase 02 tasks or acceptance proof.

Every visible Phase 02 task uses `gpt-5.6-sol` with High reasoning. The task creation API has no
fast-mode selector, so that setting is recorded unavailable/unverified.
