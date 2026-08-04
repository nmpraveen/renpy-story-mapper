# AI-first storyboard Phase 01 canary

Status: review; deterministic acceptance passed, visual acceptance pending

## User outcome

For one representative connected section of a real Ren'Py game, produce a directly openable static
storyboard that a normal reader can follow without knowing Ren'Py internals. It must preserve exact
story lines, choices, conditions, branch consequences, destinations or rejoins when supported, and
explicit uncertainty for behavior the source cannot establish.

## Contract

AI is the primary semantic analyst. It may infer scene boundaries, characters, variable meanings,
custom mechanics, route structure, choice consequences, endings, and hidden or replay content.
Every such claim must cite exact source evidence and use `high`, `medium`, or `low` confidence.

Deterministic code is the guardrail: safe read-only source recovery, stable evidence IDs, exact text,
file/line provenance, direct syntax inventory, reference validation, coverage auditing, unresolved
tracking, and deterministic HTML rendering. Parser/AI conflicts stay visible. Dynamic behavior is
never silently presented as fact.

## Canary boundary

Choose one connected section containing, where available, dialogue or narration, a menu or
conditional branch, a state variable or delayed dependency, and a custom or ambiguous construct.
Do not map the whole game, revive Story River or durable Story Map V2, build a provider platform,
add game-specific rules, polish the final UI, or start Phase 02.

## Acceptance

- The evidence index accounts for the selected source with stable IDs, exact text, provenance,
  labels, menus, arms, conditions, assignments, jumps/calls/returns, Python/custom blocks, and
  unknown statements.
- The AI profile and story analysis explain the canary with source citations, confidence, exact-line
  membership, choices, branches, consequences, supported destinations/rejoins/terminals, and
  unresolved items.
- Deterministic validation rejects fake citations, reports missing or duplicated menu arms, reports
  unaccounted source material, and preserves parser/AI disagreements.
- The static page makes order, choices, branch outcomes, and uncertainty understandable.
- Focused tests prove unfamiliar game names need no runtime changes and reusable code has no known
  game names, dialogue, or fixed counts.

## Active task ledger

| Task | Status | Next evidence |
|---|---|---|
| Align active authority with the AI-first Phase 01 contract | Complete | This goal, `MASTER_PLAN.md`, and `PROJECT_STATE.md` |
| Inspect reusable low-level modules and report Phase 01 readiness | Complete | `docs/storyboard-v2/REUSE_MAP.md` |
| Select one representative real-game canary section | Complete | `_6_2_WG_clean`, lines 218-381, recovered read-only from `v0.07_6-1_clean.rpyc` |
| Build the isolated storyboard path and generic evidence index | Complete | `src/renpy_story_mapper/storyboard/`; 159 stable evidence records |
| Generate AI profile/story analysis and deterministic validation | Complete | Publishable: 159/159, zero excluded, missing, or duplicated; byte-level SHA-256 provenance verified |
| Render and inspect the canary, then stop before Phase 02 | Blocked on visual acceptance | Five artifacts generated outside Git; Chrome policy blocked direct local-file navigation, so the user must open `index.html` |

## Current pause boundary

The accepted artifacts are in
`C:\Users\prave\Documents\RenPy Story Mapper Trials\Storyboard-V2-Phase01-20260804-accepted`.
All deterministic Phase 01 checks have passed. Phase 02 and all later work are paused. The only
remaining acceptance action is a human visual review of the directly openable `index.html` file.
