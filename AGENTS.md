# Ren'Py Storyboard repository rules

## Product

The only active product goal on this branch is a Ren'Py-game-to-readable-web-storyboard pipeline.

The reader must show exact story lines, choices, conditions, branch consequences, rejoins, loops, endings, routes, hidden/disconnected content, and unresolved dynamic behavior without requiring knowledge of Ren'Py internals.

## Architecture

Use AI as the primary semantic game analyst. AI may infer scene boundaries, character identities, variable meanings, custom mechanics, route structure, choice consequences, endings, and hidden-content classifications.

Every AI-derived claim must cite exact source evidence and carry a confidence level. Uncertain dynamic behavior must remain explicitly unresolved.

Deterministic code owns safe source recovery, stable evidence identity, exact source text, direct syntax inventory, reference validation, coverage auditing, and rendering. It acts as a guardrail and bookkeeper, not as a universal hard-coded story interpreter.

## Reuse boundary

Preserve useful low-level ingestion, source recovery, provenance, and parser work. Reuse control-flow or solver code only through narrow adapters after focused tests prove it is generic.

Do not extend Story River, the old web API, durable Story Map V2 workflows, milestone orchestration, or the hard-coded whole-game reader for the new product.

## Genericity

Reusable code must contain no known game title, character name, dialogue line, label name, expected corridor count, fixed AI batch count, or game-specific exclusion.

Game-specific discoveries belong in generated profile/analysis files.

## Development

Build one thin vertical slice before scaling. Do not create another architecture layer, provider platform, database, or broad rewrite.

Use real game source, preserve exact evidence, run focused tests, inspect generated output, and report limitations honestly. Keep legacy code untouched unless a small adapter or CLI registration is necessary.

## Codex collaboration

In this repository, Codex tasks and threads are user-visible Codex tasks shown in the app sidebar,
not internal subagents. Never substitute internal subagents when the user asks for Codex tasks or
threads. When independent investigations or implementation areas should run in parallel, dispatch
bounded, non-overlapping user-visible Codex tasks using `gpt-5.6-sol` with High reasoning unless the
user requests different settings. The coordinator owns scope, integration, and the final result.
