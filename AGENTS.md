# Repository workflow instructions

## Milestone authority

- Treat `docs/MASTER_PLAN.md` as product-scope authority.
- Treat `docs/PROJECT_STATE.md` as the current milestone pointer and lifecycle record.
- Use `.agents/skills/renpy-milestone` whenever starting, executing, reviewing, handing off, or closing a milestone.
- Keep exactly one active milestone contract. Do not infer approval from a branch name or add future product scope.
- Before broad implementation, record a PASS or REVISE decision in the milestone's `SEMANTIC_REVIEW.md`.

## Dispatch policy

- Dispatch every current milestone implementation task with model `gpt-5.6-sol`, reasoning effort `high`, and fast mode disabled.
- Use the same settings for ambiguous requirements, architecture decisions, integration, debugging, security or correctness review, and acceptance review.
- A faster model is allowed only for a future task explicitly classified as mechanical and bounded, with exact inputs, outputs, affected files, and a deterministic check. Escalate to `gpt-5.6-sol` High immediately if ambiguity or design judgment appears.
- Repository prose cannot change Codex client settings. The dispatcher, thread creator, or tool invocation must pass model, reasoning effort, and fast-mode settings explicitly. Never claim these files changed the running model; if settings cannot be selected or verified, state that limitation rather than silently downgrading.

## Completion discipline

- Keep acceptance criteria and evidence in the active milestone contract, not only in chat or a task ledger.
- Do not mark planned checks as passed. Record commands, outcomes, artifacts, review findings, integration state, and PR state.
- Keep a milestone's native Codex goal active through implementation, integration, verification, and PR preparation. Complete it only when the PR is genuinely ready under the milestone contract.
