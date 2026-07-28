# MNN - Milestone title

Status: Draft

Scope authority: `docs/MASTER_PLAN.md`, section TODO

Planning authority: `docs/MILESTONE_PLANNING_RULES.md`

## Simplicity rule

TODO: State in one sentence why this is the smallest useful user outcome. If a proposed item does
not directly support it or remove a demonstrated blocker, defer it and ask before expanding scope.

## Done condition

TODO: Narrowly restate approved scope as one observable state required for this milestone to be genuinely done and PR-ready; do not add inferred architecture or acceptance scope.

## Objective

TODO: Copy or narrowly restate the approved objective.

## Must work now

- TODO

## Useful later

- TODO: explicitly deferred improvement

## Do not build in this milestone

- TODO: production hardening, theoretical edge cases, and unrelated architecture

## Acceptance criteria

1. TODO: Keep the list to the minimum observable criteria; normally no more than five.

## Required evidence

| Criterion | Evidence required | Result / durable location |
|---|---|---|
| 1 | TODO | Pending |

## Exclusions

- TODO: Copy explicit exclusions; do not infer future scope.

## Handoff rules

- Use one Orchestra and at most two concurrent workers unless the user explicitly approves more.
- Record the user-selected model/reasoning settings for this phase; do not inherit or escalate them.
- Use affected checks while editing, one focused integration gate, sharded CI at the PR candidate,
  and one final Release/package gate unless the user explicitly requires more.
- Pause and ask before a new architecture layer or second correction loop.
- Provide the exact commit, branch or worktree, changed files, validation commands and results, assumptions, known defects, likely conflicts, and remaining acceptance work.
- Keep status at `Integration` until worker changes are integrated and reviewed.
- Keep the native Codex goal active through integration, verification, and PR preparation. Complete it only at genuine `PR ready`.
