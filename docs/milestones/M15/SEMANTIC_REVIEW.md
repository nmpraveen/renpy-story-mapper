# M15.1 Phase 02 semantic review

Date: 2026-07-24

Integration base: `f914908621efb6ccf1728e3028c6176f961e5a7e`

Decision: PASS

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
- Native goal/task `019f9676-c357-7803-a891-f03782bbb8ee` is active and exactly matches the Phase
  02 done condition.
- The task-creation API can set model and High reasoning but exposes no fast-mode field; fast mode
  will be recorded unavailable/unverified for visible tasks.
- Live product identity remains exact Luna/High/fast-off and must be verified independently before
  private transmission; visible Codex task settings do not establish live provider identity.

## Early review result and bounded correction

Visible reviewer task `019f967d-8800-79e2-9dea-5f2412f6eecf` reviewed exact clean head
`df755325edf2a679a3c0c372c9c350d9c37b989d` and returned `REVISE` with no P0/P2 and four P1s:

1. the detailed M15 master-plan section and the semantic-review goal assumption contradicted the
   active Phase 02 state;
2. branch-specific mapper events lacked a Python-owned canonical/arm-lineage binding and exact
   anchor/reachability rule;
3. the no-import rule did not name an implementable cloud/local transport seam or transitive
   dependency check; and
4. the provider transition diagram omitted the approved deliberate `local_only` mode.

This was the one permitted bounded correction. `MASTER_PLAN.md` and the goal assumption are
reconciled. `PHASE_02_DESIGN.md` now defines deterministic arm-lineage binding, ambiguous-range
rejection, exact anchor/status inputs, self-contained V2 cloud/loopback transports with a
transitive dependency gate, and a fully previewed local-only path.

The same visible reviewer rereviewed exact corrected head
`4d32f0879f3b2b8e7f498d0f8428fd3d81177195` and returned `PASS` with no unresolved P0-P2. It
confirmed all four P1s closed, the bounded correction introduced no new P0-P2, the worktree/diff
were clean, and the simple design still excludes every rejected architecture and later-phase
scope. Shared contract/failing-first work and dependency-ready Track dispatch may now begin.

PASS
