# M15.1 Phase 04 task ledger

Baseline: merged Phase 03 closeout `e715d8ae80dd1188c729a447cfabf3c45b3b7286` on synchronized
`main`; integration branch `codex/m15-phase04-full-game`.

| Task | Owner | Scope / affected area | Dependencies | Status | Evidence / handoff |
|---|---|---|---|---|---|
| Contract authoring | Phase Coordinator | GOAL, design, ledger, project pointers | User-approved plan | Complete | This contract checkpoint |
| Early semantic review | Independent visible reviewer | Requirements, authority, architecture, checks, evidence mapping | Contract checkpoint | In progress | `SEMANTIC_REVIEW.md` pending independent decision |
| Native goal and draft PR | Phase Coordinator | Goal lifecycle, integration branch, one PR | Semantic `PASS` | Pending | Goal/PR identities pending |
| Track A: authority and chunking | Visible Track A Coordinator | Occurrences, scopes, placements, frozen chunking, structural fallback | Semantic `PASS` | Pending | Separate worktree/task required |
| Track A exact-head review | Independent Track A reviewer | Correctness, coverage, exclusions, focused tests | Track A candidate | Pending | Separate visible reviewer required |
| Track B: durable workflow | Visible Track B Coordinator | Schema v7, runs/jobs/attempts/cache, consent, six workers, recovery | Semantic `PASS` | Pending | Separate worktree/task required |
| Track B exact-head review | Independent Track B reviewer | Durability, privacy, duplicate-call and fault-injection checks | Track B candidate | Pending | Separate visible reviewer required |
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
