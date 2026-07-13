# M09 — Static Story Metadata Enrichment

## Objective

Improve story-map readability by statically extracting useful names and categories from recovered
Ren'Py companion modules without executing creator code or changing authoritative story structure.

## Deliverables

- Discover a small, bounded set of companion metadata sources alongside the canonical story
  sources while keeping `scripts.rpa` and the selected story modules authoritative.
- Deterministically extract safe character aliases, default state declarations, variable display
  meanings/categories, and optional human scene titles.
- Store every metadata item with source provenance and apply it to existing speaker, state, and
  presentation surfaces without inventing graph facts or edges.
- Classify gallery/replay modules as secondary material and prevent their labels from entering the
  canonical chronology.
- Exclude images, audio, fonts, shaders, cache files, and unrelated UI code.
- Add focused synthetic fixtures, read-only MsDenvers acceptance evidence, independent review,
  Windows verification, completion documentation, a native infographic, and one unmerged PR.

## Acceptance criteria

1. No embedded Ren'Py, screen, or game Python code executes, and no selected game file is modified.
2. Character and state metadata is extracted only from supported literal/static forms; dynamic or
   ambiguous expressions are skipped with a bounded diagnostic.
3. Metadata retains locator, recovered/original line basis, source span, and content fingerprint.
4. Existing authoritative graph, route, gate, effect, and evidence hashes remain unchanged.
5. Replay/gallery labels never appear as canonical routes, while their provenance remains visible
   as secondary metadata when useful.
6. Metadata survives project close/reopen and refresh; changed companion inputs invalidate only
   their metadata.
7. Existing user-edited state display names/categories remain authoritative over extracted hints.
8. The browser shows improved readable speaker/state/scene labels without initiating AI or remote
   calls.
9. Full Windows pytest, Ruff, strict mypy, `pip check`, milestone end-to-end/browser checks, and
   independent review pass with no unresolved P0-P2 issue.
10. `GOAL.md`, `TASKS.md`, `COMPLETION_REPORT.md`, and native `INFOGRAPHIC.png` exist, and one M09
    PR is open and unmerged.

## Exclusions

- No AI-provider changes or live AI run, LM Studio, media ingestion, thumbnail system, broad AST
  evaluator, hosted service, installer, game editing, or replay-story merging.
