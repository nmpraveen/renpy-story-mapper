# Ren'Py Story Mapper project state

Updated: 2026-08-04

## Active work

- Active product direction: AI-first Ren'Py-game-to-readable-web-storyboard pipeline.
- Active phase: Phase 01 canary; no product implementation or generated canary output is claimed
  yet.
- Active goal and task ledger: [`docs/storyboard-v2/GOAL.md`](storyboard-v2/GOAL.md).
- Phase instructions: [`_storyboard_plan/02_PHASE_01_CANARY_PROMPT.md`](../_storyboard_plan/02_PHASE_01_CANARY_PROMPT.md).
- Repository rules: [`AGENTS.md`](../AGENTS.md).
- Historical record: [`docs/PROJECT_HISTORY.md`](PROJECT_HISTORY.md).
- Native Codex goal: none.

## Current decision

This branch follows the AI-first reset described in `_storyboard_plan/`:

1. deterministic code safely recovers source and builds an evidence index;
2. AI performs game reconnaissance and semantic story/branch/route/ending analysis;
3. every AI-derived claim cites exact evidence and confidence;
4. deterministic checks validate references, coverage, menu arms, and disagreements; and
5. a static web storyboard renders the canary while preserving exact lines and uncertainty.

AI may interpret unfamiliar game-specific structure, including scene boundaries, characters,
variables, custom mechanics, delayed consequences, hidden content, and likely endings. Deterministic
code owns provenance and bookkeeping, not a universal hard-coded story interpreter. Uncertain
dynamic behavior remains explicitly unresolved.

## Phase 01 status

The phase has not started beyond this authority reset. The next implementation work is limited to
one connected section of a real game and must produce the five canary files named in the active goal.
Before any full-game work, the coordinator must inspect the first useful rendered section and the
focused validation results.

The required proof is:

- a generic evidence index with stable IDs, exact text, provenance, direct syntax, and unknown or
  custom constructs;
- an AI-generated game profile and sourced story analysis;
- deterministic validation of citations, coverage, menu arms, and parser/AI disagreement; and
- a simple static page that a normal reader can follow.

## Scope controls

- Keep supplied game inputs read-only and keep generated outputs outside the game tree and Git.
- Do not add game-specific Python rules or hard-code titles, names, lines, labels, counts, batches,
  or exclusions in reusable runtime code.
- Reuse old ingestion/parser work only through focused generic proof and narrow adapters.
- Bypass Story River, the old web/API application flow, durable Story Map V2 workflows, provider
  platforms, and the hard-coded whole-game reader for this canary.
- Do not run broad legacy cleanup, build a provider platform, polish the final UI, or begin Phase 02.

## Historical boundary

The prior M16 hybrid direction, Resort benchmark, deterministic region-hierarchy repair, and known-game
Atlas remain preserved evidence in the history, hybrid-architecture, and M16 milestone documents.
They explain why this reset protects deterministic evidence and audits, but they are not current
instructions to restrict AI to editorial titles and summaries or to require the old hybrid reader.

No third-game generalization, full-game completion, or final reader choice is claimed from that prior
work or from this documentation-only commit.

## Authority

1. The user's latest explicit instruction.
2. Repository [`AGENTS.md`](../AGENTS.md) and [`MASTER_PLAN.md`](MASTER_PLAN.md).
3. The active [`Phase 01 goal`](storyboard-v2/GOAL.md).
4. This project-state pointer.

Older milestone and benchmark files are historical evidence. They do not control the active
architecture, model/provider policy, testing scope, or orchestration unless the current authority
explicitly adopts them.
