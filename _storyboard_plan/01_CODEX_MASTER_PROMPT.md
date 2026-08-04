You are the sole implementation coordinator for an AI-first reset of this repository.

Read first:

1. `_storyboard_plan/00_PRODUCT_AND_ARCHITECTURE.md`
2. `_storyboard_plan/AGENTS_REPLACEMENT.md`
3. the current repository structure and relevant low-level modules

Replace the root `AGENTS.md` with `_storyboard_plan/AGENTS_REPLACEMENT.md` on this branch. The old Git history remains the record of prior instructions.

## Mission

Build toward one product:

```bash
renpy-story-mapper storyboard GAME_PATH --output OUTPUT_DIRECTORY
```

It will turn a Ren'Py game into a readable static web storyboard with exact lines, choices, branches, consequences, rejoins, loops, endings, target routes, hidden/disconnected content, and explicit uncertainty.

## Architectural decision

This is **AI-first with deterministic guardrails**.

AI is allowed to interpret unfamiliar game-specific structure, including scene boundaries, characters, variable meanings, custom functions/statements, delayed choice consequences, endings, and hidden/replay content. Do not restrict AI to prose polishing.

Every AI conclusion must cite source evidence and confidence. Deterministic code preserves exact evidence, validates references, audits coverage, catches omissions/duplicates, and renders the result.

## Repository decision

Do not rewrite the whole repository and do not continue the old product architecture.

Create a clean new package under `src/renpy_story_mapper/storyboard/`. Reuse only the low-level stale-project modules that prove useful through narrow adapters. Bypass Story River, the old web application, durable workflow machinery, milestone orchestration, and the hard-coded whole-game reader.

Do not hard-code any game title, character, line, label, expected item count, batch count, or exclusion.

## Working method

- Make small, reviewable commits.
- Keep game files outside Git and read-only.
- Prove the design on one real canary section before full-game scaling.
- Prefer a working vertical slice over infrastructure.
- Do not ask the user to choose internal architecture.
- Do not start broad legacy cleanup.
- Stop after completing and reporting Phase 01.

First, inspect the repository and state readiness for Phase 01 in no more than one page. Include any immediate conflict with these instructions, but do not propose a competing architecture.
