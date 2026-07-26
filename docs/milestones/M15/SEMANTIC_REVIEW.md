# M15.1 Phase 03 semantic review

Date: 2026-07-25

Baseline: `e81523fe2cc42f1bc3d8dcb1a839bfd28876dfe9`

Decision: PASS

## Requirements

| Requirement / exclusion | Authority | Interpretation | Verified |
|---|---|---|---|
| Compact whole-story browser over the accepted Phase 02 core | Master plan M15; handoff done condition | Consume the exact accepted core; do not remap or reconstruct story boundaries | Yes |
| AI synthesis is broad compression only | Master plan M15; handoff AI contract | Existing anchors may be grouped/titled/summarized; mechanics and topology are immutable Python inputs | Yes |
| Complete chronological success and fallback | Handoff criteria 7 and 10 | Successful synthesis has 5-7 sections; omitted anchors are placed deterministically; invalid/unavailable synthesis falls back to all events once | Yes |
| Exact local mechanics and nesting | Handoff criteria 6 and 8 | Choices/arms/conditions/effects/destinations/rejoins come from the accepted core; parent lineage alone owns nested placement | Yes |
| M12-backed path and existing Detail/Evidence/source navigation | Master plan two-level map; handoff path behavior | Story anchors bind to current deterministic targets; unresolved paths expose known prefix without invented connectivity | Yes |
| Minimal durable project integration | Handoff minimal integration | Reuse generic project payload transactions; store one current core and zero/one synthesis keyed to source/authority identity; reject stale records | Yes |
| Normal-flow responsive story page | Master plan route map; handoff browser behavior | Story Map V2 is primary; bounded semantic HTML, local stacked arms, preserved selection/context, no third level | Yes |
| One bounded exact Terra call | Handoff provider authorization | One preview-bound Terra/High/fast-off submission, no retry/auditor/mapper/local/model substitution | Yes |
| Privacy, safety, and outside-Git private artifacts | Master plan non-negotiables; handoff criteria 14 | No raw Ren'Py resend, code execution, private fixture/text in Git, protected mutation, or remote browser assets | Yes |
| Separate visible tracks and independent reviews | Handoff required topology | Track A first for shared seams; Tracks B/C may run in parallel afterward; each and final candidate require exact-head review | Yes |
| Future scope and rejected architecture excluded | Master plan M14/M15; handoff criteria 18 | No Phase 04/05, M14, scheduler/recovery, migration/retirement, installer, Stage H/E, hierarchy/compiler/repair system | Yes |

## Architecture boundaries

- Authority and invariants:
  - The accepted Phase 02 `StoryMapCore`, 12 event anchors, eight outcome anchors, and
    `ChoiceMechanic` records are immutable story/mechanics input.
  - M10 remains authoritative for canonical nodes, edges, facts, evidence, source locations, and
    deterministic reachability. M11 may provide existing scene/occurrence context. M12 alone solves
    entry-to-target paths. Existing inspection/scene APIs own Detail/Evidence and qualified source
    navigation.
  - Synthesis identity is prose-independent and binds the accepted core/source/authority identity,
    versioned request fields, prompt/schema, provider settings, and payload hash.
- Components allowed to change:
  - `src/renpy_story_mapper/story_map_v2/` for Phase 03 contracts, synthesis, storage, projection,
    and path/detail adapters.
  - `src/renpy_story_mapper/web/contracts.py` and `web/api.py` for bounded read-only V2 endpoints.
  - `src/renpy_story_mapper/web/static/` for the primary semantic Story Map V2 page and local API
    client/validation.
  - Generalized `tests/test_story_map_v2_phase03_*.py` and synthetic fixtures.
  - M15 lifecycle/design records and private outside-Git acceptance tooling/artifacts.
- Components that must not change:
  - Historical Stage H/E packages (`narrative_map`, `organization`, `narrative`) as a dependency
    or implementation base; Phase 02 mapper meaning/overlay/planner behavior; M10/M11/M12 solver
    semantics; source ingestion/execution safety; private source/archive/project bytes.
  - Legacy maps may remain for compatibility but are not the default Story Map V2 page.
- External, privacy, safety, or platform boundaries:
  - Windows CPython 3.12 remains authority. Browser assets are local and loopback-only. No game,
    creator, screen, or Ren'Py Python executes.
  - The one cloud payload contains only approved story-facing core fields and mechanics digest.
    Private artifacts, response, screenshots, and source paths remain outside Git.
  - Task creation can select `gpt-5.6-sol` and High reasoning but exposes no fast-mode selector;
    task fast mode is unavailable/unverified. Live Terra identity is verified separately.

## Expected files and tests

| Area | Expected files / components | Focused and regression checks |
|---|---|---|
| Shared Phase 03 contracts | `story_map_v2/phase03_contracts.py`, synthesis schema, package exports | Exact keys/types, anchor identity, chronological order, no duplicates/foreign IDs, 5-7 success sections |
| Synthesis and fallback | `story_map_v2/synthesis.py`, provider preview/transport adapter | Omission placement, empty/reverse/unknown rejection, unavailable/invalid complete fallback, payload-field privacy, one-call ceiling |
| Project storage | `story_map_v2/persistence.py` using existing generic payload transactions | Core/synthesis round trip, authority/hash binding, stale rejection, reopen with zero provider construction |
| Browser projection | `story_map_v2/presentation.py` | All events once, local/nested choice ownership, exact arm order/mechanics/rejoins, collapsed notes, no raw technical IDs as story content |
| Path and evidence | `story_map_v2/navigation.py` over M12 and current detail/source adapters | Five target classes, unresolved prefix, exact anchor/target binding, event/arm detail and qualified source links |
| API | `web/contracts.py`, `web/api.py` | Read-only map/path/detail routes, bounded validation, stale/unavailable behavior, bootstrap route exposure |
| Browser | `web/static/index.html`, `app.js`, `api.js`, `contract.js`, `styles.css`, manifest/docs as needed | Primary V2 load, selection/context preservation, keyboard focus, stacked arms, 100%/200% no horizontal overflow, no remote requests |
| Architecture/privacy | V2 import gate and diff scan | No Stage H/E dependency, no private strings/files, no source execution, local assets only |
| Integration/static | Existing relevant M10-M12/source-navigation tests, Ruff, strict mypy, JS syntax, JSON/schema, whitespace | Focused plus relevant regressions before private preview; exact pushed-head workflow is repository-wide gate |

## Acceptance evidence plan

| Criterion | Proof required | Command or artifact |
|---|---|---|
| 1 | Exact fetched baseline and tracked-clean state | Recorded preflight output |
| 2-4 | Active goal/contract, gate, visible tasks/worktrees/reviewers | Goal result, task IDs, commits, reviewer verdicts |
| 5-7 | Synthesis boundary and complete success/fallback | Schema/validation tests and private count report |
| 8-10 | Exact/nested mechanics, rejoins, complete fallback | Generalized projection/browser tests and private audit |
| 11 | Exact preview/provider identity/one call | Outside-Git preview, hashes, execution ledger |
| 12 | Durable reopen and stale rejection | Persistence tests and private zero-call reopen report |
| 13 | Responsive/selection accessibility | Browser harness at 100%/200% and screenshots |
| 14 | Privacy/immutability/no remote or execution | Fingerprint audit, containment/import/network checks |
| 15 | Explicit user approval | Coordinator task response |
| 16 | No final P0-P2 and exact-head checks | Final reviewer verdict and GitHub run |
| 17-18 | Complete lifecycle/PR/exclusions | Completion report, exact commit/PR state, diff audit |

## Assumptions and conflicts

- The user request to implement the dedicated handoff explicitly starts approved Phase 03 and
  authorizes its one narrowly defined private synthesis call after the required preview/gates.
- Local and remote `main` exactly match clean Phase 01/02 merge `e81523f`; untracked `.playwright-
  cli/`, prior handoffs, `output/`, and `tmp/` are preserved user/private content and do not make
  the tracked baseline dirty.
- The accepted package exists at the handoff path. Its core is complete 1/1 with 12 events, four
  choices, eight outcomes, zero validation failures, and matching source/archive/project hash,
  size, and nanosecond mtime.
- The existing generic project payload store is sufficient for the phase's minimal persistence;
  a new scheduler, retry queue, or database migration is neither required nor allowed.
- Event and branch anchors already contain canonical node/destination information. Track C must
  fail honestly when no exact M12 destination binding exists rather than manufacture a target.
- The handoff requires user-visible Codex worktrees. The available task API supports model and
  High reasoning but no fast-mode selector; this limitation is recorded rather than treated as a
  contract relaxation.
- No authority conflict remains after updating the active M15 lifecycle pointer from completed
  Phase 02 to this Phase 03 contract.

## Gate decision

The approved scope has one observable done condition, the accepted input and protected boundaries
are verified, the shared seams assign deterministic and AI responsibilities without adding a new
semantic compiler, expected files/checks can prove every criterion, and no unresolved scope or
architecture decision requires user input. Broad implementation may start only after the matching
native goal is created and recorded.

PASS
