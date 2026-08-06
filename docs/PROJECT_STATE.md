# Ren'Py Story Mapper project state

Updated: 2026-08-06

## Active work

- Active product direction: AI-first Ren'Py-game-to-readable-web-storyboard pipeline.
- Active phase: Phase 01.1 contract/evidence hardening is complete. The corrected real canary is
  publishable with exact coverage and has passed normal-browser visual acceptance. Later phases
  remain paused pending explicit user acceptance and direction.
- Active goal and task ledger: [`docs/storyboard-v2/GOAL.md`](storyboard-v2/GOAL.md).
- Phase instructions: [`_storyboard_plan/02_PHASE_01_CANARY_PROMPT.md`](../_storyboard_plan/02_PHASE_01_CANARY_PROMPT.md).
- Repository rules: [`AGENTS.md`](../AGENTS.md).
- Private progress map: [Workflow Atlas](https://renpy-workflow-atlas.nmpraveen.chatgpt.site).
- Historical record: [`docs/PROJECT_HISTORY.md`](PROJECT_HISTORY.md).
- Native Codex goal: Phase 01.1 recovery and acceptance, fulfilled by the evidence below.

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

The isolated `src/renpy_story_mapper/storyboard/` path now implements a parser-independent
source-line ledger with parser annotations, one canonical evidence/profile/analysis contract,
exact-once semantic ownership and per-scene/per-arm coverage, status-aware uncertainty validation,
semantic scene destinations with source/target evidence, structural parent closure, public-path
redaction, nearest-branch physical ownership, one bounded validator-guided AI repair, and
normal-reader-first HTML rendering. The accepted real-game canary covers `_6_2_WG_clean` lines
218-381 from `v0.07_6-1_clean.rpyc`.

The accepted five-file Phase 01.1 output is outside Git at
`C:\Users\prave\Documents\RenPy Story Mapper Trials\Storyboard-V2-Phase01_1-20260805-203052-825-literal-rules-recovery`.
Validation is publishable with 159/159 accountable records covered, zero errors, exclusions,
unaccounted records, or duplicate memberships. All five parser-derived arms are complete at
100/100, 2/2, 17/17, 31/31, and 2/2 records. The original `scripts.rpa` SHA-256 remained
`053ABB13454180A2CF9B0AA762E33DEDA98CF027D9C1E39082F5795982720303` before and after.

The Phase 01.1 focused verification passes: 134 `test_storyboard*.py` tests, Ruff, strict mypy, and
Draft 2020-12 checks for both storyboard schemas. It includes parser-failure ledger recovery,
branch ownership, dynamic status semantics, schema acceptance, scene ordering, nested span closure,
canonical renderer topology, path redaction, provider transport projection, one-repair enforcement,
and the known-game/fixed-count scan.

The accepted `index.html` was inspected through a loopback server in the normal in-app browser.
Story order, exact lines, both menu arms, nested conditions, consequences, uncertainty, and the
shared fadeout continuation were readable with no horizontal overflow, clipping, or broken images.
A sibling PNG was captured outside the five-file output directory. No later phase has started.

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
work or from this Phase 01 canary.

## Authority

1. The user's latest explicit instruction.
2. Repository [`AGENTS.md`](../AGENTS.md) and [`MASTER_PLAN.md`](MASTER_PLAN.md).
3. The active [`Phase 01 goal`](storyboard-v2/GOAL.md).
4. This project-state pointer.

Older milestone and benchmark files are historical evidence. They do not control the active
architecture, model/provider policy, testing scope, or orchestration unless the current authority
explicitly adopts them.

The active-phase coordinator is the sole Workflow Atlas publisher for coordinated work. Worker tasks
report status and evidence to the coordinator and do not edit or deploy the Atlas. Accepted future
plans, execution starts, integrated passes, failures, and attention states must be reflected in the
published map before the coordinator closes the phase.
