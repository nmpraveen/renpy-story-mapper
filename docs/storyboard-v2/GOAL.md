# AI-first storyboard Phase 01 canary (Phase 01.1 hardening)

Status: Phase 01.1 combined implementation locally integrated and review-pending; focused checks passed; real-canary rerun and visual acceptance pending

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

Phase 01.1 hardens this boundary with a parser-independent physical source-line ledger, one
canonical evidence/profile/analysis contract for requests, replay, validation, rendering, and
repair, exact-once ownership of semantic leaves across scenes, arms, continuations, and explicit
unresolved/exclusion buckets, and public-artifact path redaction. Embedded Python and runtime-
computed behavior remain unresolved by default; custom or unknown constructs require a cited
rationale before an interpretation can be resolved.

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
- Focused regressions cover parser fallback, branch ownership, resolved consequences, custom versus
  Python semantics, scene ordering, nested parent closure, path redaction, line-window closure,
  schema acceptance, and known-game/fixed-count scanning.

## Active task ledger

| Task | Status | Next evidence |
|---|---|---|
| Align active authority with the AI-first Phase 01 contract | Complete | This goal, `MASTER_PLAN.md`, and `PROJECT_STATE.md` |
| Inspect reusable low-level modules and report Phase 01 readiness | Complete | `docs/storyboard-v2/REUSE_MAP.md` |
| Select one representative real-game canary section | Complete | `_6_2_WG_clean`, lines 218-381, recovered read-only from `v0.07_6-1_clean.rpyc` |
| Build the isolated storyboard path and generic evidence index | Complete | `src/renpy_story_mapper/storyboard/`; 159 stable evidence records |
| Generate AI profile/story analysis and deterministic validation | Complete | Publishable: 159/159, zero excluded, missing, or duplicated; byte-level SHA-256 provenance verified |
| Complete bounded Phase 01.1 contract and evidence repairs | Locally integrated; review pending | 68 focused storyboard tests, Ruff, strict mypy, and both Draft 2020-12 schema checks pass; no real cloud canary or screenshot run |
| Rerun the real canary and inspect the rendered page, then stop before Phase 02 | Pending separate acceptance worker and visual acceptance | Existing accepted artifacts predate Phase 01.1 and were not regenerated in this task |

## Current pause boundary

The prior accepted artifacts are in
`C:\Users\prave\Documents\RenPy Story Mapper Trials\Storyboard-V2-Phase01-20260804-accepted`.
They remain read-only baseline evidence and were not regenerated after Phase 01.1. The combined
Phase 01.1 implementation is locally integrated and review-pending. The bounded implementation
checks pass, but the real cloud canary rerun and visual inspection of its generated `index.html`
remain pending. Phase 02 and all later work stay paused.
