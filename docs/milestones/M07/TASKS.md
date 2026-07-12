# M07 Worker Tasks

Baseline: `e24509c`

Milestone branch: `codex/m07-two-level-route-map`

Normal implementation and review tasks use GPT-5.6 Sol with High reasoning and fast mode disabled.
Only actual story-analysis provider calls use GPT-5.6 Luna with High reasoning and fast mode
disabled.

Worker rows are added immediately after each user-visible Codex task is created.

| Task ID | Title | Responsibility | Branch/worktree | Status |
|---|---|---|---|---|
| `019f57a5-dd89-7200-82fc-14afbe602dda` | Deterministic Route Map and durable model | Route projection, pre-AI scopes, checkpoint/coverage contracts, migrations, deterministic assembly, focused tests | `codex/m07-route-model` in dedicated Codex worktree | Complete; integrated as `b572575`, `7b44be5`, and `5a64946` after complete-topology correction |
| `019f57a5-dd89-7200-82fc-14cb9fa622cc` | Resumable parallel AI orchestration | Eight-to-twelve-worker scheduler, throttling, repair bound, cache, budgets, per-attempt usage, cancellation/resume, mocked tests | `codex/m07-parallel-ai` in dedicated Codex worktree | Core integrated as `f1e7a93`; persistent project adapter follow-up active |
| `019f57a5-dd9a-7c42-a842-0aaabd5bd962` | M07 fixtures and acceptance contracts | Route-semantics fixtures, mocked provider timelines, two-level Chrome acceptance harness, new tests only | `codex/m07-fixtures-acceptance` in dedicated Codex worktree | Complete; integrated as `34c0260`, contract boundary aligned in `35c25fa` |
