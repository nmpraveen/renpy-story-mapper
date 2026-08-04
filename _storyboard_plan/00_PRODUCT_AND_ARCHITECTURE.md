# Product and architecture direction

## Only product goal

Give the system a Ren'Py game and receive a complete, readable web storyboard showing:

- the story in sensible reading order;
- exact dialogue and narration;
- every meaningful choice and conditional branch;
- what choices lead to later scenes;
- branch consequences, rejoins, loops, and endings;
- routes to important scenes and endings;
- hidden, replay, bonus, and disconnected story content; and
- honest warnings where dynamic code prevents certainty.

The output should read like a storyboard, not like compiler output.

## Core architecture

Use an **AI-first analyst with deterministic guardrails**.

```text
Ren'Py game
  -> safe source recovery and evidence index
  -> AI game reconnaissance and game profile
  -> AI story/branch/ending analysis with citations
  -> deterministic reference and coverage audit
  -> AI repair of specific gaps
  -> static web storyboard
```

### AI is responsible for interpretation

AI may infer:

- characters and aliases;
- scene boundaries and narrative grouping;
- meanings of unfamiliar variables;
- custom statements and helper functions;
- route and relationship mechanics;
- important versus technical text;
- choice consequences and delayed dependencies;
- likely endings and hidden/replay content;
- plain-language story summaries; and
- uncertain hypotheses about dynamic behavior.

AI is not limited to writing titles and summaries.

### Deterministic code is responsible for evidence and bookkeeping

Code should handle:

- safe unpacking and read-only source access;
- stable IDs for files, labels, statements, menus, arms, and source spans;
- exact source text and direct Ren'Py syntax facts;
- search and cross-reference tools for the AI;
- validation that cited evidence exists;
- checks for missing or duplicated menu arms and source material;
- coverage reports and unresolved-item tracking; and
- deterministic HTML generation.

Code should not try to encode every game's narrative conventions through permanent `if game == ...` rules.

## Evidence rule

Every AI-derived structural or semantic claim must include:

- source evidence references;
- confidence: `high`, `medium`, or `low`; and
- an unresolved explanation when certainty is not possible.

AI conclusions may supplement or challenge parser-derived assumptions. Conflicts must remain visible until resolved. Neither side silently overwrites the other.

## Game-specific adaptation

Every game receives a generated `game-profile.json` describing its conventions, such as:

- entry points;
- character definitions and aliases;
- route and relationship variables;
- custom statement/function meanings;
- scene-boundary conventions;
- ending and replay/gallery patterns; and
- unresolved dynamic mechanisms.

Game-specific knowledge belongs in this generated profile and analysis output, not in reusable Python source.

## What to reuse from the stale repository

### Reuse first

- safe ingestion and archive handling;
- RPA/source recovery where reliable;
- source hashing and provenance;
- low-level source inventory;
- parser output that preserves exact text and source locations.

### Reuse only after a focused proof

- control-flow extraction;
- state tracking;
- canonical graph logic;
- route-solving algorithms.

Wrap these behind small adapters. Copying one generic algorithm is preferable to importing an entire legacy subsystem.

### Bypass for the new product

- Story River and the old web application;
- `web/api.py` and Qt-dependent application flow;
- durable Story Map V2 workflow/repository machinery;
- old milestone orchestration and provider platforms;
- the current hard-coded whole-game corridor/reader path;
- fixed packet counts, fixed batch counts, and known-game exclusions.

## New product location

Build the new path in a clean package such as:

```text
src/renpy_story_mapper/storyboard/
```

The final command should eventually be:

```bash
renpy-story-mapper storyboard GAME_PATH --output OUTPUT_DIRECTORY
```

The final output should be a directly openable static `index.html` plus machine-readable analysis and audit files.
