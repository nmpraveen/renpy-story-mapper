# M15.1 Phase 04 task ledger

Baseline: merged Phase 03 closeout `e715d8ae80dd1188c729a447cfabf3c45b3b7286` on synchronized
`main`; integration branch `codex/m15-phase04-full-game`.

| Task | Owner | Scope / affected area | Dependencies | Status | Evidence / handoff |
|---|---|---|---|---|---|
| Contract authoring | Phase Coordinator | GOAL, design, ledger, project pointers | User-approved plan | Complete | This contract checkpoint |
| Early semantic review | Independent visible reviewer | Requirements, authority, architecture, checks, evidence mapping | Contract checkpoint | Complete | Repeated exact-head `PASS` at `eb1d2672b76d1445a2dbbb770b1d2cd152d45bf2`; prior `REVISE` history and corrected consent conflict remain recorded in `SEMANTIC_REVIEW.md`; P0=P1=P2=0 |
| Native goal and draft PR | Phase Coordinator | Goal lifecycle, integration branch, one PR | Semantic `PASS` | Complete | Native goal active on coordinator task `019f7fe2-eeaa-7622-b3eb-f53d5bd5f749`; draft [PR #30](https://github.com/nmpraveen/renpy-story-mapper/pull/30) is open and unmerged |
| Track A: authority and chunking | Visible Track A Coordinator | Occurrences, scopes, placements, frozen chunking, structural fallback | Semantic `PASS` | In progress | Coordinator `019fa00d-1e55-79e0-95b0-c88f8fd89919`; A1 `019fa00e-c8e5-7141-8c83-d043b27d9d34`; A2 `019fa00e-c8e9-7422-bce8-adc0b692ff40`; separate worktrees, product work underway |
| Track A exact-head review | Independent Track A reviewer | Correctness, coverage, exclusions, focused tests | Track A candidate | In progress | Task `019fa00e-c967-7e71-a7e4-151e1cfcb498`; review matrix preparation only until exact integrated head is supplied |
| Track B: durable workflow | Visible Track B Coordinator | Schema v7, runs/jobs/attempts/cache, consent, six workers, recovery | Semantic `PASS` | In progress | Coordinator `019fa00d-1e77-7fd3-93d5-ee9761a5f662`; B1 `019fa00f-8e20-7382-8dc9-2c1ce5d39975`; B2 `019fa00f-b94c-7af1-9b10-1b67c64ea6fb`; separate worktrees, product work underway |
| Track B exact-head review | Independent Track B reviewer | Durability, privacy, duplicate-call and fault-injection checks | Track B candidate | In progress | Task `019fa00f-dad0-7b13-9454-9c9b44a0d098`; review matrix preparation only until worker and integrated exact heads are supplied |
| A/B integration seam | Phase Coordinator | Integrate reviewed heads; freeze plan/job/publication interfaces | A/B reviews pass | Pending | Integration commit and focused gate pending |
| Track C: assembly and API | Visible Track C Coordinator | Selective review, sections, rollups, generations, scalable APIs | Frozen A/B seam | Pending | Separate worktree/task required |
| Track C exact-head review | Independent Track C reviewer | Semantic validation, paging/navigation, compatibility | Track C candidate | Pending | Separate visible reviewer required |
| Track D: browser and acceptance | Visible Track D Coordinator | Workflow UI, lazy reader, NEW diff, browser/scale/real-run harness | Frozen A/B seam and C fixtures | Pending | Separate worktree/task required |
| Track D exact-head review | Independent Track D reviewer | Browser races, accessibility, privacy, scale geometry | Track D candidate | Pending | Separate visible reviewer required |
| Final integration and verification | Phase Coordinator | Integrated diff, focused/regression/scale/private acceptance | C/D reviews pass | Pending | Exact commands/artifacts pending |
| Final cross-track review | Independent visible reviewer | Exact integrated head, exclusions, P0-P3 | Integrated candidate | Pending | Separate visible reviewer required |
| User visual approval | User / Phase Coordinator | Exact-head 100%/200%/narrow private screenshots | Final review pass | Pending | Approval pending |
| Release and PR readiness | Phase Coordinator | Full Windows gate, CI, completion report, ready unmerged PR | Acceptance and approval | Pending | Pending |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`.
