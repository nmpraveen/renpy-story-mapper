# M15.1 Phase 05 - AI story timeline

Status: In progress

Scope authority: `docs/MASTER_PLAN.md`, M15 / M15.1 semantic Story Map correction

Planning authority: `docs/MILESTONE_PLANNING_RULES.md`

## Simplicity rule

Turn the already working full-game data into one readable scrolling story timeline; anything that
does not improve that view, preserve exact mechanics/evidence, or protect local read-only input is
out of scope.

## Done condition

Opening the accepted MsDenvers project shows a clean chronological vertical story timeline with a
small set of AI-organized major events, visible inline choices and outcomes, persistent routes,
important state changes, rejoins and endings, plus a meaningful selected-path rail and direct
Detail/Evidence access. A person can understand the rough story by scrolling instead of browsing
425 technical sections. The result uses local-only AI for editorial organization and Python-owned
deterministic facts for mechanics.

## Objective

Restore the missing information architecture: editorial story grouping above the accepted 425
local summaries and a default reader that makes the whole story, branches, routes, and rejoins easy
to follow while scrolling.

## Must work now

- Reuse the accepted 425 local summaries and current deterministic events, choices, effects,
  routes, rejoins, endings, paths, and evidence. Do not rerun the existing chunk summaries.
- Add one bounded local-AI editorial grouping/synthesis step that produces roughly 12-30 ordered
  major story groups and a coherent whole-story overview. Python must validate complete,
  exactly-once, chronological membership and must remain authoritative for every mechanical fact.
- Make the grouped chronological timeline the default reader: major-event cards on a vertical
  spine, subordinate beats, inline branch arms/outcomes, compact route/state/rejoin/ending markers,
  and no horizontal page scrolling.
- Make the selected-path rail narratively meaningful by prioritizing selected choices,
  requirements, outcomes, and important effects over technical traversal steps.
- Keep the 425 chunk/job rows available only as collapsed diagnostics and preserve existing
  Detail/Evidence navigation.

## Useful later

- Human-edited day/chapter names where the game has no authoritative day hierarchy.
- Exact imitation of an old mock's colors or layout and broader visual polish.
- Deleting or redesigning sunk Phase 04 durability/workflow infrastructure.

## Do not build in this milestone

- A new database, migration, scheduler, workflow, API version, schema family, or recovery system.
- Cloud story-content AI, automatic model installation/loading, or game/Ren'Py execution.
- A freeform graph canvas, formal proof system, exhaustive semantic replay, or publication-grade
  prose guarantees.
- New mechanical facts inferred by AI or game-specific hard-coded chapter/day assumptions.

## Acceptance criteria

1. The accepted full-game project opens into one readable vertical timeline with 12-30 ordered
   major groups; every accepted source section belongs to exactly one group and the 425-row view is
   collapsed diagnostics rather than primary navigation.
2. Local AI supplies concise group titles, summaries, and the whole-story overview; Python rejects
   missing, duplicate, reordered, foreign, or mechanically invented membership/facts and overlays
   exact choices, routes, effects, rejoins, endings, and evidence.
3. Scrolling alone makes the main story and important branches legible at normal desktop width and
   200% browser zoom, without horizontal page scrolling; route/rejoin/ending distinctions are
   visually obvious.
4. Selecting an event/choice shows a meaningful path made of narrative choices, requirements,
   outcomes, and important effects, while Detail/Evidence still opens the exact existing record.
5. A current MsDenvers screenshot and browser walkthrough are accepted by the user; focused tests,
   one integrated Story Map gate, final review, sharded PR CI, and one final Windows Release/package
   gate pass while source input remains read-only and story content remains local.

## Required evidence

| Criterion | Evidence required | Result / durable location |
|---|---|---|
| 1 | Real-project group count and exactly-once coverage check | Strict final pass: generation `5daf4e7e...bab7857` has 24 ordered `story-group:` sections, exact 425/425 source-section and event coverage, and every stored membership span matches its raw AI endpoint without repair or rebinding |
| 2 | Local-AI transcript/projection plus Python rejection tests | `output/m15-phase05-strict-final-local-20260728-003600`; 425 cache hits, six grouping calls plus one rollup, 7/7 accepted, 36,246 input and 3,793 output tokens, maximum call total 6,897 tokens, strict gap/overlap/foreign/oversize rejection tests, and zero cloud calls |
| 3 | Current desktop and 200% browser screenshots with scroll-width check | `output/playwright/m15-phase05-strict-final-local-20260728-003600`; normal desktop story width is 1265/1265 px and effective 200% is 705/705 px, all 24 groups are collapsed by default, scrolling alone reaches group 24, and there is no horizontal overflow |
| 4 | Browser path and Detail/Evidence walkthrough | Selected `Yes` then `She ignores him`; the rail shows selected choices and requirements with technical traversal collapsed, Detail/Evidence opens `game/v0.01_clean.rpy:155`, and Back restores the selected arm and expanded group |
| 5 | User verdict, focused/integrated/final commands, CI and Release results | Strict artifact validation and browser walkthrough pass; final Sol/High comparison is `READY` with P0=P1=P2=0; exact-head gate passes 104 Story Map tests plus 2 workflow-contract tests, Ruff, strict mypy, Node syntax, and diff checks. User verdict, final integrated review, Release/package, sharded PR CI, and PR remain pending |

## Exclusions

- No exact human-authored Day 1/Day 2 hierarchy is promised where the game does not provide one.
- No cloud provider call or transmission of private story content.
- No broad cleanup merely because existing Phase 04 code is complex.
- No merge without separate explicit user approval.

## Dispatch settings

- Orchestra: this user-visible task; its runtime model and fast-mode state are not exposed here and
  are not claimed.
- Completed implementation workers and the early reviewer used explicit `gpt-5.6-sol` with Ultra
  reasoning. Per the user's latest dispatch instruction, the comparison evaluator and every new
  worker/reviewer use `gpt-5.6-sol` with High reasoning. The task API exposes no fast-mode selector,
  so fast mode remains unavailable/unverified.
- One Orchestra, two concurrent implementation threads, one early semantic reviewer, and one final
  integrated reviewer.

## Handoff rules

- The backend thread owns the grouping/projection seam and focused Python tests. The browser thread
  owns the scrolling composition and focused static/browser tests. They must not redesign each
  other's layer.
- Preserve the existing reader/API shapes where possible; pause before a new contract family.
- Run affected checks while editing, one focused integration gate, sharded CI once at the PR
  candidate, and one final Release/package gate.
- Show the real project as soon as the shortest vertical path works; fix only demonstrated
  comprehension blockers after that inspection.
- Keep the native Codex goal active through integration, verification, user acceptance, and PR
  preparation. Complete it only when the PR is genuinely ready.
