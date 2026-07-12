# M07 Goal — Two-Level Route Map and Resumable Parallel AI

Status: Active

Baseline: `e24509c` (M06.5 merged through PR #10)

Branch: `codex/m07-two-level-route-map`

## Objective

Replace the three-level browser hierarchy with exactly two user-visible levels—a bounded Route Map
and one Detail/Evidence workspace—and make optional story enrichment scope-based, parallel,
resumable, measurable, and safely partial without weakening deterministic authority.

## Deliverables

- Deterministic chronological Route Map with compact milestones, forks, proven merges, detours,
  persistent route lanes, loops, gates, effects, and distinct terminals.
- One direct Detail/Evidence workspace with a local context strip and no third navigation level.
- Deterministic route scopes completed before AI; technical coverage represented as corridors or
  coverage metadata instead of singleton cards.
- Consent-gated GPT-5.6 Luna High orchestration starting with eight workers, optionally ramping to
  twelve, with adaptive throttling and no more than two concurrent repairs.
- Durable per-scope checkpoints, cancellation/resume, normalized cache identity, incremental
  call/token accounting, adaptive timeouts/budgets, and deterministic serialized assembly.
- Honest AI-versus-technical coverage, ETA ranges, partial validated results, review, and apply.
- Windows/Chrome acceptance, independent review, completion report, and native infographic.

## Acceptance criteria

- Windows CPython 3.12 full pytest, Ruff, strict mypy, `pip check`, and `git diff --check` pass.
- Completion order does not change deterministic output; validated scopes survive cancellation and
  resume; unchanged replay performs zero provider calls.
- Throttling, budgets, adaptive timeouts, repair bounds, per-attempt accounting, and partial
  acceptance are exercised with deterministic provider fixtures.
- Route Map initial density is about 30 meaningful nodes and preserves correct gates, effects,
  detours, persistent routes, merges, loops, terminals, and unresolved behavior.
- Detail/Evidence is directly reachable; 100%/200% zoom, fonts, accessibility, keyboard behavior,
  and bounded rendering pass in Chrome on Windows.
- No provider is constructed on open/render. Cloud story transmission requires fresh explicit
  consent and uses only GPT-5.6 Luna with High reasoning and fast mode disabled.
- Deterministic authority hashes are unchanged by organization.
- Independent review has no unresolved P0-P2 or accepted P3 correctness/security finding.
- `GOAL.md`, `TASKS.md`, `COMPLETION_REPORT.md`, native `INFOGRAPHIC.png`, and one unmerged M07 PR
  exist. No later milestone is started.

## Exclusions

No full MsDenvers cloud rerun without separately confirmed scope/budget, LM Studio product work,
hosted service, accounts, telemetry, installer, public release, macOS support, game editing, or
automatic cloud calls.

