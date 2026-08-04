# AI-first storyboard Phase 01 canary

Status: active; documentation reset complete, implementation pending

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
| Inspect reusable low-level modules and report Phase 01 readiness | Pending | Bounded readiness note; no competing architecture |
| Select one representative real-game canary section | Pending | Read-only source scope and rationale |
| Build the isolated storyboard path and generic evidence index | Pending | New package, reuse map, and evidence output |
| Generate AI profile/story analysis and deterministic validation | Pending | Cited analysis, validation report, and focused tests |
| Render and inspect the canary, then stop before Phase 02 | Pending | `index.html`, review findings, limitations, and commit |
