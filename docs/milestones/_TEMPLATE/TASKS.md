# MNN task ledger

Baseline: TODO

| Task | Owner | Scope / affected area | Dependencies | Status | Evidence / handoff |
|---|---|---|---|---|---|
| Semantic review | One lightweight reviewer | Confirm smallest useful outcome, existing seams, exclusions, and lean evidence | Approved scope | Pending | `SEMANTIC_REVIEW.md` |
| Worker 1 | TODO | One bounded independent vertical-path outcome | Semantic review `PASS` | Pending | TODO |
| Worker 2, only if useful | TODO | One non-overlapping bounded outcome | Frozen seam | Pending | TODO |
| Real example and user review | Orchestra | Run the smallest real acceptance example and pause for feedback | Integrated vertical path | Pending | TODO |
| Integration and verification | Orchestra plus one final reviewer | Integrated milestone diff and lean acceptance | User accepts real result | Pending | TODO |
| PR readiness | TODO | Review, evidence, completion report, PR | Verification passed | Pending | TODO |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`. Record why a task is blocked and what unblocks it.

Use one Orchestra, no more than two concurrent workers, one early review, and one final integrated
review by default. Record user-selected model/reasoning settings before dispatch.
