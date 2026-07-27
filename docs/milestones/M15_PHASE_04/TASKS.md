# M15.1 Phase 04 lean task ledger

Baseline: branch `codex/m15-phase04-full-game`, product checkpoint `2995d99`, draft PR #30 open and
unmerged.

Only statuses `Pending`, `In progress`, `Blocked`, and `Complete` are used below.

| Task | Owner | Small bounded outcome | Dependencies | Status | Evidence / handoff |
|---|---|---|---|---|---|
| Scope reset | Current coordinator | Replace the production-grade contract with the user-approved lean outcome and future planning rules | User direction | Complete | Revised `GOAL.md`, design, project rules, planning guide, and resume prompt; no product code or provider work |
| Fresh lightweight semantic gate | Visible task `019fa18a-816a-77b2-99b1-1717ef117a54` | Confirm the revised plan reuses current code and adds no production-grade requirements | Scope-reset checkpoint | Complete | Exact clean head `2bcdd02`; seven YES answers; `PASS`; explicit `gpt-5.6-sol` Medium; fast-mode selector unavailable/unverified |
| Existing Phase 04 foundation | Historical Tracks A-D and integration | Planning/chunking, durable jobs, mapping runner, semantic/reader/browser foundations, CI shards | Historical contract | Complete | Integrated commits through `2995d99`; old per-track reports remain historical evidence, not current acceptance authority |
| Backend/API vertical path | Visible task `019fa18f-e895-71d3-ac9e-49e81ef77c7b` | Approved run → accepted summaries → simple sections/overview → published generation; advertise existing workflow commands | Fresh semantic `PASS` | Complete | Clean worker head `3723da9`, integrated as `29f4378`; 141 focused workflow/reader tests and 19 adjacent API tests passed with Ruff and strict mypy |
| Website vertical path | Visible task `019fa18f-f055-7411-ac72-acbddf2b4f8d` | Preview/consent/progress/cancel/resume controls open the existing chronological reader | Existing frozen workflow HTTP v2 contract | Complete | Clean worker heads `cdfd37a` and `b4572aa`, integrated as `b8bf018` and `2776b99`; focused browser/asset checks passed, including reopen/resume state |
| Lean integration review | Visible reviewer `019fa3b6-3a89-7bd0-83f4-0ec607ab869e` | Review the integrated vertical path against the eight lean criteria | Both workers integrated | Complete | Same reviewer closed its one stale-lifecycle P2 after the bounded correction. Exact `44844601…` rereview: `PASS`, P0=0, P1=0, P2=0; 48 focused tests plus architecture, Ruff, mypy, and diff checks passed; worktree clean. |
| Real MsDenvers check | Orchestra with explicit user consent | Run supported workflow, inspect representative story/branch/path samples, show result to user | Integrated path and zero-submit preview | Complete | Exact approved run retained 425 calls, 0 accepted AI results, 19 structural and 406 indeterminate results. Provider-free publication produced generation `b7f05d2…f940`: 425 sections, 1,770 events, 693 choices, 719 arms, 163 endings, and 59 landmarks. Live website shows choices/effects, late state, Path, and relative Detail/Evidence; AI prose remains honest placeholders. |
| Blocker-only correction | Visible task `019fa38c-0524-7eb1-9ccf-4dedc9189af9` plus prior website task | Fix only problems demonstrated by the real check | User feedback | Complete | Integrated `3cdc7e6`, `3ec5f93`, `afe9157`, `13c82d4`, and `157c496`: terminal structural publication, privacy-safe effect omission, reader discovery, fail-closed evidence compatibility, and visible relative locator. Worker used explicit Sol/Medium; fast unavailable/unverified. |
| Local summary observability | Orchestra | Keep raw local prompt/response evidence outside Git, show compact per-query progress, and remove exact-format work from the local model | User request and demonstrated local failures | Complete | `4426a58`; private opt-in JSONL transcript, collapsed 425-row website table, one-summary prompt v3, Python-owned membership/mechanics/length binding, and narrow escaped-mechanics privacy-scan correction. Focused gate: 116 passed plus Ruff, strict mypy, JavaScript syntax, and whitespace. Corrected live run reached 31/31 accepted with zero rejects/provider errors at the evidence checkpoint. |
| Final lean gate and PR readiness | Orchestra | Focused tests, user screenshots, sharded CI, one Release/package gate, evidence, ready PR #30 | User accepts output | In progress | Prior Release on `4484460`: 1,773 passed plus every quality/package stage. Latest correction gate: 116 passed plus static checks. The active local run, user usefulness approval, intended-head final gate, and one push/CI check remain; leave PR open and unmerged. |

## Orchestra policy

- One user-visible Orchestra task owns the goal and manages the tasks above.
- No more than two implementation workers run concurrently.
- For this resumption, all workers and reviewers use explicit `gpt-5.6-sol` and Medium reasoning;
  the user authorized the unavailable fast-mode selector to remain recorded as unverified.
- Monitor completions and blockers only. Do not continuously poll commentary or healthy CI.
- When a task proposes a new schema, protocol, scheduler, recovery system, review tier, or unrelated
  hardening, pause and ask the user.
