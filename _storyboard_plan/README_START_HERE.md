# Start here: AI-first Ren'Py Storyboard reset

## The decision

Do **not** start an unrelated repository and do **not** keep extending the old product architecture.

Use the **same Git repository**, but create a **fresh branch in a separate worktree folder**. This keeps the useful ingestion/parser history while isolating the new product from the stale application.

Recommended setup:

```bash
cd PATH_TO_CURRENT_RENPY_STORY_MAPPER

git status
# Commit or stash any unfinished work before continuing.

git worktree add ../renpy-story-mapper-ai -b ai-storyboard-v2
cd ../renpy-story-mapper-ai
```

This gives you:

- the old folder, left untouched as a reference;
- a new physical folder for the AI-first version; and
- the same Git history, tests, and reusable low-level code.

Do not manually copy the whole repository into a disconnected new project. That loses history and encourages duplicated bugs.

## What to copy into the new worktree

Copy this prompt pack into:

```text
_storyboard_plan/
```

Then start one persistent Codex task in the new worktree and paste:

1. `01_CODEX_MASTER_PROMPT.md`
2. after Codex reports readiness, `02_PHASE_01_CANARY_PROMPT.md`

Also let Codex replace the root `AGENTS.md` with `AGENTS_REPLACEMENT.md` on this branch.

## What happens in Phase 01

Phase 01 is deliberately small. It proves the architecture on one representative section of a real game.

Codex will:

- identify exactly which old modules are worth reusing;
- create a clean new `storyboard` package;
- produce a source/evidence index;
- use AI to infer game-specific meaning, scenes, variables, branches, and custom behavior;
- require source evidence and confidence for AI conclusions;
- audit the result for missing choices and invalid references; and
- render a basic static HTML storyboard for the canary section.

It will **not** yet map the entire game, polish the final UI, build a provider platform, or delete legacy code.

## What to give Codex

Give Codex the filesystem path to one known Ren'Py game. Use a game you already understand well enough to spot obvious errors. Keep the game outside Git.

After Phase 01, return with the files listed in `04_WHAT_TO_BRING_BACK_AFTER_PHASE_01.md`.
