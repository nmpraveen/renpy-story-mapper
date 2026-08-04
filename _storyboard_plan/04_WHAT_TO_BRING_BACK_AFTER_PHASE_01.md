# What to bring back after Phase 01

Return with either the whole updated repository zip or, at minimum:

1. Codex's Phase 01 report and commit ID.
2. `docs/storyboard-v2/REUSE_MAP.md`.
3. The new `src/renpy_story_mapper/storyboard/` package.
4. Focused Phase 01 tests.
5. The generated files:
   - `evidence-index.json`
   - `game-profile.json`
   - `story-analysis.json`
   - `validation-report.json`
   - `index.html`
6. A screenshot of the rendered canary page, if convenient.
7. Any disagreement Codex found between AI interpretation and the existing parser/control-flow output.

Use this message when returning:

> Phase 01 is complete. Review the implementation and the generated canary storyboard. Check whether the AI was given enough authority, whether the evidence/coverage guardrails are useful, what stale code is actually worth retaining, and what should change before Phase 02.
