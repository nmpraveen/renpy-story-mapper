# M15.1 Phase 04 lean task ledger

Baseline: branch `codex/m15-phase04-full-game`, product checkpoint `2995d99`, draft PR #30 open and
unmerged.

Only statuses `Pending`, `In progress`, `Blocked`, and `Complete` are used below.

| Task | Owner | Small bounded outcome | Dependencies | Status | Evidence / handoff |
|---|---|---|---|---|---|
| Scope reset | Current coordinator | Replace the production-grade contract with the user-approved lean outcome and future planning rules | User direction | Complete | Revised `GOAL.md`, design, project rules, planning guide, and resume prompt; no product code or provider work |
| Fresh lightweight semantic gate | Visible task `019fa18a-816a-77b2-99b1-1717ef117a54` | Confirm the revised plan reuses current code and adds no production-grade requirements | Scope-reset checkpoint | Complete | Exact clean head `2bcdd02`; seven YES answers; `PASS`; explicit `gpt-5.6-sol` Medium; fast-mode selector unavailable/unverified |
| Existing Phase 04 foundation | Historical Tracks A-D and integration | Planning/chunking, durable jobs, mapping runner, semantic/reader/browser foundations, CI shards | Historical contract | Complete | Integrated commits through `2995d99`; old per-track reports remain historical evidence, not current acceptance authority |
| Backend/API vertical path | Visible task `019fa18f-e895-71d3-ac9e-49e81ef77c7b` | Approved run → accepted summaries → simple sections/overview → published generation; advertise existing workflow commands | Fresh semantic `PASS` | In progress | Branch `codex/m15-p4-backend-vertical`, clean separate worktree, exact base `21d80d2`; Python/backend files and focused fake-provider tests only |
| Website vertical path | Visible task `019fa18f-f055-7411-ac72-acbddf2b4f8d` | Preview/consent/progress/cancel/resume controls open the existing chronological reader | Existing frozen workflow HTTP v2 contract | In progress | Branch `codex/m15-p4-website-vertical`, clean separate worktree, exact base `21d80d2`; static website files and focused browser tests only |
| Lean integration review | One separate visible reviewer | Review the integrated vertical path against the eight lean criteria | Both workers integrated | Pending | One exact integrated-head verdict; no per-worker reviewer tree |
| Real MsDenvers check | Orchestra with explicit user consent | Run supported workflow, inspect representative story/branch/path samples, show result to user | Integrated path and zero-submit preview | Pending | Private artifacts outside Git; usefulness review before any polish |
| Blocker-only correction | Responsible worker | Fix only problems demonstrated by the real check | User feedback | Pending | One bounded pass; second design loop pauses for user decision |
| Final lean gate and PR readiness | Orchestra | Focused tests, user screenshots, sharded CI, one Release/package gate, evidence, ready PR #30 | User accepts output | Pending | Leave PR open and unmerged |

## Orchestra policy

- One user-visible Orchestra task owns the goal and manages the tasks above.
- No more than two implementation workers run concurrently.
- For this resumption, all workers and reviewers use explicit `gpt-5.6-sol` and Medium reasoning;
  the user authorized the unavailable fast-mode selector to remain recorded as unverified.
- Monitor completions and blockers only. Do not continuously poll commentary or healthy CI.
- When a task proposes a new schema, protocol, scheduler, recovery system, review tier, or unrelated
  hardening, pause and ask the user.
