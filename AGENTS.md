# Repository workflow instructions

## Product simplicity authority

- **THE PRODUCT IS A QUICK, CRUDE SCRIPT-TO-STORY CHECKER, NOT A PRODUCTION-GRADE SYSTEM.**
- The primary outcome is simple: load Ren'Py files and quickly see the rough whole story, choices,
  branch routes, important state changes, and rejoins.
- Build the smallest thing that makes that outcome work on the current real game. Do not add
  enterprise durability, exhaustive proof, extreme-scale infrastructure, new protocol versions,
  or defensive matrices unless a demonstrated current-game blocker requires them.
- Preserve useful existing implementation, but do not finish previously planned complexity merely
  because it already appears in an old contract or design.
- If a proposed change does not directly improve script-to-story output, remove a demonstrated
  blocker, or protect private read-only inputs, stop and ask the user before proceeding.

## Milestone authority

- Treat `docs/MASTER_PLAN.md` as product-scope authority.
- Treat `docs/PROJECT_STATE.md` as the current milestone pointer and lifecycle record.
- Use `.agents/skills/renpy-milestone` whenever starting, executing, reviewing, handing off, or closing a milestone.
- Keep exactly one active milestone contract. Do not infer approval from a branch name or add future product scope.
- Follow the skill's single early semantic-review gate before broad implementation.

## Dispatch policy

- The user selects the coordinator and worker model/reasoning settings for each phase or resumption.
  Never inherit model settings from an earlier milestone or silently escalate them.
- For the next Phase 04 resumption, implementation and review tasks must explicitly use
  `gpt-5.6-sol` with Medium reasoning and fast mode disabled. If a selector is unavailable, report
  that limitation instead of claiming the setting.
- Use one user-visible Orchestra task to guard scope, make decisions, integrate, and report at
  milestone checkpoints. It may dispatch at most two independent implementation tasks at once
  unless the user explicitly approves a different topology.
- The Orchestra must not perform continuous commentary monitoring or start speculative work while
  another task runs. When scope, necessity, or product value is uncertain, pause the goal and ask.
- Repository prose cannot change Codex client settings. The dispatcher, thread creator, or tool invocation must pass model, reasoning effort, and fast-mode settings explicitly. Never claim these files changed the running model; if settings cannot be selected or verified, state that limitation rather than silently downgrading.

## Quota-aware testing and review

- During implementation, run only tests and static checks that cover the changed files and direct
  integration seam.
- Run one focused integrated Story Map gate at a meaningful checkpoint. Use the repository-wide
  sharded CI workflow only for a PR candidate or another explicitly useful integration boundary.
- Run the full Windows Release/package gate once on the final intended PR head, not after every
  worker, correction, commit, or push.
- Use one early semantic review and one final integrated review by default. Add another review only
  for a concrete unresolved correctness, privacy, or safety risk.
- Do not spend agent quota waiting on healthy CI. Check it once after completion or when it needs
  action.

## Completion discipline

- Keep acceptance criteria and evidence in the active milestone contract, not only in chat or a task ledger.
- Do not mark planned checks as passed. Record commands, outcomes, artifacts, review findings, integration state, and PR state.
- Keep a milestone's native Codex goal active through implementation, integration, verification, and PR preparation. Complete it only when the PR is genuinely ready under the milestone contract.
