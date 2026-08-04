# Phase 01: prove the AI-first vertical slice

Use the real Ren'Py game path supplied by the user.

## Objective

Prove that this repository can combine reusable low-level extraction with AI interpretation on one representative connected section of a real game, without adding game-specific Python rules.

This is a canary, not the full product.

## Required work

1. Create `docs/storyboard-v2/REUSE_MAP.md` listing:
   - modules reused now;
   - modules wrapped or copied through an adapter;
   - modules deliberately bypassed; and
   - why each decision was made.

2. Create the new isolated `src/renpy_story_mapper/storyboard/` package.

3. Build a generic evidence index for a selected real-game section. It must preserve stable IDs, exact source text, file/line provenance, labels, menus, choice arms, conditions, assignments, jumps/calls/returns, Python/custom blocks, and unknown statements.

4. Choose a canary section containing, where available:
   - dialogue or narration;
   - at least one menu or conditional branch;
   - at least one state variable or delayed dependency; and
   - at least one custom or ambiguous construct.

5. Use AI reconnaissance to generate `game-profile.json` for the relevant game conventions. Use AI analysis to generate `story-analysis.json` containing readable scenes, exact-line membership, choices, branches, consequences, destinations/rejoins/terminals where supported, source evidence, confidence, and unresolved items.

6. Implement deterministic validation that at minimum:
   - rejects nonexistent evidence references;
   - reports missing or duplicated menu arms;
   - reports source material in the canary that is unaccounted for;
   - keeps parser/AI disagreements visible; and
   - does not silently convert uncertain dynamic behavior into fact.

7. Render a simple static `index.html` for the canary. It need not be visually polished, but a normal reader should understand the scene, choices, branch outcomes, exact lines, and uncertainty.

8. Add focused tests proving:
   - unfamiliar character/variable/label names do not require code changes;
   - a fake evidence citation is rejected;
   - an omitted choice arm is reported; and
   - no known-game names, dialogue, or fixed counts exist in reusable runtime code.

## Do not do in Phase 01

- Do not map the whole game.
- Do not build the final UI.
- Do not build a general AI-provider platform.
- Do not revive the old workflow or Story River.
- Do not delete legacy systems.
- Do not spend the phase on broad refactoring or CI cleanup.

## Deliverables

Produce a single phase output directory containing:

```text
evidence-index.json
game-profile.json
story-analysis.json
validation-report.json
index.html
```

Commit the implementation and report:

- commit ID;
- reused and bypassed modules;
- exact canary scope;
- commands/tests run;
- what AI inferred successfully;
- what deterministic validation caught;
- known failures or uncertainties; and
- paths to all five deliverables.

Then stop. Do not begin Phase 02.
