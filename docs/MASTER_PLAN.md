# Ren'Py Story Mapper master plan

Updated: 2026-08-06

## Product goal

Give the system a Ren'Py game or readable script and receive a complete, readable static web
storyboard. A normal reader should understand the story in sensible order, exact dialogue and
narration, meaningful choices, conditions, branch consequences, rejoins, loops, endings, routes,
hidden or disconnected content, and behavior that remains unresolved because the source is dynamic.
The output should read like a storyboard rather than compiler output.

The eventual command is:

```text
renpy-story-mapper storyboard GAME_PATH --output OUTPUT_DIRECTORY
```

The first proof is deliberately smaller: one representative connected section from one real game.

## Active direction: AI-first with deterministic guardrails

The active product architecture is:

```text
Ren'Py game
  -> safe source recovery and evidence index
  -> AI reconnaissance and game profile
  -> AI story, branch, route, and ending analysis with citations
  -> deterministic reference and coverage audit
  -> AI repair of specific gaps when needed
  -> static web storyboard
```

AI is the primary semantic game analyst. It may infer scene boundaries, character identities and
aliases, variable meanings, custom statements and helper functions, route mechanics, choice
consequences, endings, hidden or replay content, and plain-language story explanations. It is not
limited to titles and prose polishing.

Deterministic code is the guardrail and bookkeeper. It owns safe read-only ingestion, stable
evidence identity, exact source text, file and line provenance, direct syntax inventory,
cross-reference checks, coverage auditing, unresolved-item tracking, and rendering. It must not
become a permanent hard-coded interpreter of one game's narrative conventions.

Every AI-derived structural or semantic claim must cite exact source evidence and carry a
`high`, `medium`, or `low` confidence. If the source cannot establish dynamic behavior, the result
must say so explicitly. Parser/AI disagreements remain visible until resolved; neither side
silently overwrites the other.

## Active phase: Phase 01 canary

Phase 01 proves a thin vertical slice on one representative connected section of a real Ren'Py
game. It combines reusable low-level extraction with AI interpretation without adding game-specific
Python rules. It is a canary, not a whole-game mapping or a final reader.

The canary must include, where the supplied game makes them available, dialogue or narration, a
menu or conditional branch, a state variable or delayed dependency, and a custom or ambiguous
construct. The evidence index must preserve stable IDs, exact source text, provenance, labels,
menus, choice arms, conditions, assignments, jumps, calls, returns, Python/custom blocks, and
unknown statements.

The canary output is one directly openable static directory containing:

```text
evidence-index.json
game-profile.json
story-analysis.json
validation-report.json
index.html
```

The normal reader must be able to follow the selected section, see exact lines and choices, read
branch outcomes and consequences, and recognize uncertainty. Validation must reject nonexistent
evidence citations, report missing or duplicated menu arms, report unaccounted source material,
keep parser/AI conflicts visible, and prevent uncertain dynamic behavior from becoming fact.

## Reuse and isolation boundary

Reuse first only the low-level safe ingestion, archive/source recovery, hashing/provenance, source
inventory, and exact-text parser work that proves useful. Reuse control-flow, state, canonical-graph,
or solver code only through a narrow adapter after focused generic tests prove it is safe.

The new path belongs under `src/renpy_story_mapper/storyboard/`. Story River, the old web API and
Qt flow, durable Story Map V2 workflows, milestone orchestration, provider platforms, and the
hard-coded whole-game reader are bypassed for this phase. Do not delete them or perform broad
legacy cleanup. Reusable code must contain no known game title, character, dialogue line, label,
expected count, fixed AI batch count, or game-specific exclusion.

## Phase 01 acceptance

Phase 01 is useful only when all of these are true:

1. One real canary section is identified and its source remains read-only.
2. Exact source material and stable evidence references survive into the analysis.
3. AI semantic claims include evidence, confidence, and explicit unresolved explanations where
   required.
4. Deterministic validation catches invalid citations, choice-arm omissions or duplication,
   unaccounted source material, and visible parser/AI disagreements.
5. The rendered static page communicates story order, choices, branch outcomes, and uncertainty.
6. Focused tests show unfamiliar names do not require code changes and reusable runtime code has no
   game-specific names, dialogue, or fixed counts.

Stop after the canary is inspected and reported. Do not start Phase 02 or scale to the full game
until the user accepts the Phase 01 proof.

## Later direction

Only after Phase 01 is useful may the project decompose a full game into evidence scopes, analyze
cross-scope dependencies, repair concrete coverage gaps, and choose the smallest reusable reader
surface. Full-game scaling, polished navigation, one-command integration, unseen-game
generalization, and gradual legacy cleanup are later work, not current acceptance requirements.

## Progress visibility

The private Workflow Atlas is the user-facing view of the accepted roadmap and live execution state.
Accepted future phases appear there as not built; active work is marked in progress; integrated gates
are marked passed, failed, or needing attention with evidence. When a phase uses coordinated worker
tasks, only the coordinator may update or publish the Atlas. Workers report status and evidence back
to that coordinator so the map stays consistent instead of receiving competing updates.

The coordinator updates and publishes the Atlas at planning, phase start, material gate transitions,
and phase completion. Atlas presentation never replaces repository evidence or deterministic
acceptance; it is the readable projection of that authority.

## Historical boundary

The earlier M16 hybrid/Resort work remains valuable history: deterministic facts, source evidence,
the region-hierarchy repair, and the known-game Atlas proof are preserved in
`docs/PROJECT_HISTORY.md`, `docs/HYBRID_APPROACH.md`, and the M16 milestone files. They are not
the active Phase 01 contract and do not establish generalization for this AI-first canary.

## Completion

The product succeeds when a new Ren'Py game can be turned into a coherent, source-grounded,
auditable storyboard without a game-specific product rewrite, while semantic interpretation,
deterministic evidence, and unresolved behavior remain clearly distinguishable.
