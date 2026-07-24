# M15.1 Phase 02 semantic review

Date: 2026-07-24

Integration base: `f914908621efb6ccf1728e3028c6176f961e5a7e`

Decision: REVIEW PENDING

## Requirement verification

The active contract is the Phase 02 objective approved in
`docs/handoffs/M15_PHASE_02_STORY_MAP_V2_CORE_REWRITE.md`. It preserves the master plan's static
authority for connectivity, choices, requirements, effects, source evidence, and routes while
allowing AI to write approximate event and branch-outcome meaning.

The proposed design is frozen in `PHASE_02_DESIGN.md`. It is a new bounded
`story_map_v2` package and is materially simpler than the rejected Stage H/E pipeline: contiguous
source chunks, one compact mapper response, a Python mechanics overlay, and one chronological core
record. It contains no new product level, AI topology authority, atom/evidence allocation,
hierarchy compiler, repair protocol, exact-prose replay, browser, or durable full-game scheduler.

## Architecture authority and boundaries

- M10 canonical records own exact nodes, edges, regions, facts, source evidence, and reachability.
- Existing M11 scene/lane/choice ownership may be consumed only as already-derived structural
  context; it is not exposed to the mapper as atoms or membership work.
- M12 owns route-to-target status where a route is requested.
- Current safe ingestion, project/storage, provider isolation, cancellation, and source navigation
  may be reused.
- The supported V2 path must not import `narrative_map`, `narrative`, or `organization`; historical
  Stage H/E code and records do not change in Phase 02.
- Private evaluation material, external AI outputs/images, historical responses, screenshots,
  unrelated files, secrets, and game assets are excluded from Git and mapper packets.

## Expected files and checks

- New: `src/renpy_story_mapper/story_map_v2/` records, source adapter, chunk planner, mapper
  serialization/validation, mechanics overlay, assembler, provider policy, and minimal export.
- New: focused `tests/test_story_map_v2_*.py` plus generalized synthetic fixtures/resources.
- Current lifecycle documents are updated; historical product code is not deleted or repurposed.
- Focused checks cover chunk boundaries/limits, mapper range/key validation, deterministic overlay,
  stable anchors, partial assembly, cloud/refusal/fallback states, cancellation, and architecture
  imports.
- Relevant M10/M11/M12, provider privacy/isolation, source navigation, and package import checks
  run after integration.
- Private acceptance proves exact Luna identity/settings, six/eight call ceilings, chronology,
  four choices/eight arms, target anchors, immutability, and containment.

## Acceptance evidence map

| Criteria | Evidence |
|---|---|
| 1 | Goal service result and lifecycle pointers |
| 2 | Separate visible early-review task verdict |
| 3 | Dependency/import test and integrated diff review |
| 4 | Planner tests plus private packet ledger/token counts |
| 5-6 | Generalized overlay/fixture tests and schema tests |
| 7-10 | Exact preview/confirmation, fake-provider matrix, call ledger |
| 11-13 | Private core/preview, mechanics audit, anchors, before/after fingerprints |
| 14 | Focused/regression results and final exact-head review |
| 15-16 | Completion report, implementation commit, PR/check state, exclusions audit |

## Assumptions and resolved conflicts

- The current coordinator is the new Phase 02 coordinator requested by the handoff.
- The existing integration worktree is clean at the required branch and may be used directly; no
  replacement integration branch is created.
- Local history being 136 commits ahead of the remote is expected rejected-history preservation,
  not permission to push before acceptance.
- The native goal service currently has no active goal. A new goal will be created only after this
  contract is locked and will exactly match the Phase 02 done condition.
- The task-creation API can set model and High reasoning but exposes no fast-mode field; fast mode
  will be recorded unavailable/unverified for visible tasks.
- Live product identity remains exact Luna/High/fast-off and must be verified independently before
  private transmission; visible Codex task settings do not establish live provider identity.

## Unresolved review decision

A separate visible Early Contract Reviewer must inspect the contract and design. Broad product
implementation and Track A/Track B dispatch remain paused until that reviewer returns `PASS`.
Only one bounded design correction and rereview is allowed.

REVIEW PENDING
