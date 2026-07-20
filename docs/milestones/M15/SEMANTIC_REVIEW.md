# M15 semantic review

Date: 2026-07-20

Baseline: `a447a4eefbd7c093bdb2767e62a393805af068ac`

Decision: PASS

Amendment decision (2026-07-20): PASS

## Verification amendment - exact-bound technical coverage correction

The final integrated review proved that the approved leading setup and an adversarial meaningful
pre-Day choice can be identical under the frozen M10 topology and M11 atom facts. M10 also has no
categorical Prologue marker at the approved line-27 anchor. Continuing to infer the cut would hide
valid story in some projects, while leaving the setup visible would fail the approved M15 outcome.

The user's 2026-07-20 authorization of all M15 corrections therefore activates the Master Plan's
existing user-correction authority for this one ambiguity. M15 may persist an exact-authority-bound
**leading technical coverage correction** with these constraints:

- it reuses the full `AuthorityBinding` (`source_generation`, M10 schema/hash, and M11 atom
  schema/hash), has a correction schema and rule version, a stable normalized ID/hash, a bounded
  privacy-safe non-empty reason, qualified locators, and an explicit ordered atom-ID tuple;
- for reconstructed `ordered_atoms`, the tuple must equal `ordered_atoms[:n]` where
  `0 < n < len(ordered_atoms)`. The qualified locators must resolve uniquely to that same tuple.
  Unknown, duplicate, stale, mismatched, ambiguous, non-prefix, or out-of-order corrections are
  rejected and keep ambiguous story-facing content visible;
- it may impose exactly one deterministic derived corridor/event partition between the corrected
  prefix and `ordered_atoms[n]`, while preserving complete, ordered, non-overlapping, exactly-once
  atom ownership. It changes only that partition, `technical_atom_ids`, coverage state, and
  collapsed presentation;
- it cannot create, delete, reorder, or redirect M10 edges, choices, arms, rejoins, gates,
  effects, terminals, or unresolved records; change ownership anywhere outside the one corrected
  prefix cut; create an AI candidate; or grant AI any membership or topology authority;
- without a valid correction, deterministic construction remains conservative and keeps
  story-facing content visible;
- the approved MsDay1 correction is resolved from qualified source locators for reconstructed
  lines 1-26, stores no private text, and is written only to an acceptance working copy. The
  original source and comparison project remain byte-, size-, and timestamp-identical;
- the correction is a versioned M15 payload and participates in normalized identity/cache
  invalidation. It does not mutate or reinterpret stored M10/M11/M12/M13 authority.

This amendment does not change the done condition. It supplies the missing explicit semantic
authority while preserving M10 as the sole topology authority and keeping no-correction behavior
safe for other projects. Failing-first contract, persistence, stale-binding, adversarial, exact
private, API, browser, and independent rereview evidence are required before integration resumes.
Atomic persistence/reopen, absent/stale/corrupt/mismatched/ambiguous rejection, correction identity
in corridor/map/job/cache invalidation, working-copy API application, conservative no-correction
visibility, and regenerated 100%/200% evidence are explicit acceptance gates.

## Requirements

| Requirement / exclusion | Authority | Interpretation | Verified |
|---|---|---|---|
| Readable two-level Story Map | `docs/MASTER_PLAN.md` §§1, 4 and approved plan §§1, 4-5 | Replace micro-scenes with chronological human events; Detail/Evidence is the only second level | Yes |
| M10 deterministic authority | Master rules 3-8; approved plan §3 | M10 owns topology, choices, conditions, effects, merges, terminals, unresolved behavior, and source evidence | Yes |
| M11 atoms, not M11 scene authority | Approved plan §§2-3 | Reuse ordered evidence atoms; current M11 boundaries/membership/titles are comparison inputs only | Yes |
| User technical-coverage correction | Master Plan core records; user correction authorization; verification amendment above | An exact-bound user correction may classify only a strict leading atom prefix as collapsed technical coverage; it has no topology or AI authority | Yes |
| Bounded AI responsibility | Master rules 8-10; approved plan §§6-7 | AI decides adjacent soft boundaries and later titles/summaries only; Python owns membership and quotient edges | Yes |
| Exact private Day 1 scope | Approved plan §§3-4, 10 and `MsDay1/SOURCE_MANIFEST.json` | Hash/line anchors are acceptance evidence only; private story text never enters Git or prompts as a golden answer | Yes |
| Nested temporary choices | Master §4; approved plan §§4-7 | Local choices remain inside their event cluster and visibly reconnect at proven M10 rejoins | Yes |
| Visible M12 retirement with compatibility | Approved plan §5 | Hide/remove route-solving controls and requests; retain backend, persistence, readers, stored results, and M13 citation navigation | Yes |
| Visible legacy AI retirement with fallback | Approved plan §5 | New map has independent state/contracts; retain legacy storage/API and safe old-project fallback | Yes |
| Provider consent and zero-call normal journey | Master rules 9-10; approved plan §§3, 9-10 | No cloud call without fresh manifest and separate consent; open/navigation/replay remain zero-call | Yes |
| Read-only/no-execution safety | Master §§3, 10; approved plan §§3, 10 | No game writes, game/Ren'Py/Python execution, runtime tracing, private-content commit, or authority weakening | Yes |
| Separate coordinated worktrees and reviews | Master §9; approved plan §8 | Coordinator freezes contracts, then dispatches three user-visible tasks and final read-only review | Yes |
| Windows and browser acceptance | Master §9; approved plan §§9-12 | CPython 3.12, quality/package gates, exact Day 1, 100%/200% Chrome, evidence and immutability | Yes |
| PR remains unmerged | Master §9; approved plan §§8, 12 | One M15 PR is prepared and left for explicit user merge approval | Yes |
| Explicit exclusions | Approved plan §3 and `GOAL.md` | Full MsDenvers, M14, installer/public distribution, media/Q&A/automation/editing, unauthorized provider calls remain out | Yes |

## Architecture boundaries

- Authority and invariants: `canonical_graph.py`, `canonical_graph_contract.py`,
  `inspection_projection.py`, `control_flow.py`, `m11_scene_model.py`, and existing persisted
  M10/M11/M12/M13 payloads remain source inputs or compatibility authorities. New code may adapt
  them but must not mutate their ownership or reinterpret their edges.
- Frozen new domain boundary: `src/renpy_story_mapper/narrative_map/` owns versioned contracts,
  deterministic corridor construction, boundary candidates, deterministic event assembly,
  Narrative Map projection, persistence adapters, service orchestration, and presentation records.
  Concrete modules are `contracts.py`, `corridors.py`, `assembly.py`, `persistence.py`,
  `projection.py`, `service.py`, and `presentation.py`; `__init__.py` exposes a narrow public API.
- AI boundary: versioned boundary and event-summary prompt/schema resources live under dedicated
  `narrative_map/prompts/` and `narrative_map/schemas/` surfaces. The sterile provider/process
  boundary is reused beneath the new semantic contract; legacy M13 schemas and behavior are not
  rewritten.
- Persistence boundary: use new versioned Narrative Map collections through the existing atomic
  canonical payload mechanism unless failing-first evidence proves a migration necessary. No
  migration may delete or rewrite old organization, route, narrative, claim, correction, or
  evidence records.
- API boundary: `web/api.py` and `web/contracts.py` may expose bounded Narrative Map lifecycle,
  projection, and detail routes. They cannot grant arbitrary filesystem access, provider calls on
  GET/open/navigation, or browser-side topology authority.
- Browser boundary: `web/static/index.html`, `app.js`, `api.js`, `contract.js`, `graph.js`, and
  `styles.css` may make Story Map the default and hide legacy controls. New state must not use
  `state.aiPage`; JavaScript renders server-provided deterministic relationships only.
- Components that must not be deleted or semantically repurposed: M12 model/solver/service/
  persistence and stored-result reader; M13 M12-citation support; existing M07/M08/M13 persistence
  and compatibility APIs; M10 authority; M11 historical scene payloads; source recovery and
  ingestion safety boundaries.
- External/privacy/platform boundaries: Windows CPython 3.12 is runtime authority; loopback-only
  browser security remains intact; no remote assets or implicit provider calls; private
  `MsDay1/` and its story text remain ignored/untracked and read-only; the original archive is not
  needed for product work and, if accessed for final evidence, is fingerprinted before/after.

## Expected files and tests

| Area | Expected files / components | Focused and regression checks |
|---|---|---|
| Shared contracts | New `narrative_map/contracts.py`, package exports, versioned schemas | Identity/hash/serialization, unknown enum/ID/bounds rejection, authority-binding tests |
| Deterministic Track A | New `corridors.py`, `assembly.py`, `projection.py`, `presentation.py`; M10/M11 adapters | Linear/pose-change/detour/nested choice/persistent lane/call/loop/terminal/unresolved fixtures; membership and quotient provenance |
| AI Track B | Versioned prompts/schemas, projection, persistence, validation, workflow/service integration | Adjacent-only candidates, hard-boundary exclusion, one schema repair, partial failure, cancel/reopen/resume/cache, zero-call replay, privacy/authority rejection |
| API and persistence | New versioned collections and bounded web contracts/routes | Atomic publication, old-project reopen, unchanged legacy payloads, no provider on GET/open/navigation, security regressions |
| Browser Track C | Existing static HTML/JS/CSS/manifest plus new Narrative Map rendering modules if needed | Default Story Map, nested choice/rejoin geometry, no legacy controls/requests, exact Detail/Evidence, search/pan/zoom/fit/keyboard, 100%/200% |
| Compatibility | Existing M12/M13 services, presentation, browser citation handling, legacy project fixtures | Stored M12 result opens from M13 citation; legacy projects do not crash; backends remain compatible |
| Private acceptance | Opt-in `MsDay1` runner/tests/scripts with no committed story text | Exact hash/line anchors, 165-scene comparison, golden cluster/order export, screenshots, pre/post fingerprints |
| Repository gates | Existing Release script/workflow, package and browser asset checks | Full pytest, Ruff, strict mypy, `pip check`, JS syntax, whitespace, wheel/install/import, assets, notices |
| Evidence/docs | `docs/milestones/M15/`, `docs/deferred/`, private artifacts outside Git | Exact commands/results/hashes/reviews, screenshots, text export, completion report, native infographic |

## Acceptance evidence plan

| Criterion | Proof required | Command or artifact |
|---|---|---|
| 1-5 | Stable contracts, deterministic ownership/topology, exact provenance, negative validation | Focused M15 contracts/corridor/assembly/projection tests and golden synthetic payloads |
| 6-8 | Exact private input, anchors, golden chronological shape, technical collapse | Opt-in provider-free Day 1 runner; pre/post manifest; visible-order export; screenshots |
| 9-11 | Exact evidence and preserved legacy M12/M13/old-project behavior | API/UI tests plus real-Chrome traversal and zero-request counters |
| 12-13 | Durable jobs, repair/failure isolation, cancel/reopen/resume, zero-call replay/navigation | Fake-provider fault matrix, persistence reopen tests, counters, optional separately approved consent record |
| 14 | Usable graph and controls at 100%/200% | Real Chrome reports, layout diagnostics, keyboard run, screenshots |
| 15-16 | Legacy authority/stored data/source/archive immutability and no execution | Before/after payload/source/archive hashes, size/timestamps, execution/network counters |
| 17 | Repository and package health | Exact focused then full Windows Release commands with exit codes/counts/timings and wheel inspection |
| 18 | Independent review and resolved findings | Track A/B/C exact-head reports and final no-edit integrated review |
| 19 | Human acceptance and PR readiness | Completion report, final text export/screenshots, infographic, PR URL and remote state |

## Assumptions and conflicts

- The user explicitly approved the planning handoff as M15 on 2026-07-20; M14 remains deferred.
- The old project-state and master next-action text said no successor was active. This lifecycle
  staleness is resolved by activating M15 and is not a product-scope conflict.
- Master §5 contained a stale “Level 3” sentence despite §4's explicit two-level supersession. The
  higher, newer two-level rule controls; the sentence is corrected to Detail/Evidence.
- The original archive is absent from `MsDay1/`; its manifest records SHA-256
  `053abb13454180a2cf9b0aa762e33deda98cf027d9c1e39082f5795982720303`, 2,140,282 bytes, and
  timestamp nanoseconds `1783041076000000000`. Final archive immutability is required only if the
  external archive is accessed; the extracted source is always checked before/after acceptance.
- Read-only discovery recorded 773 M01 nodes, 788 edges, 773 M11 atoms, 165 M11 scenes, nine M11
  temporary structures, one chapter, 174 presentation nodes, 115 minimum-run boundaries, and 35
  unresolved-safety boundaries. These are comparison evidence, not production thresholds.
- The thread-creation surface supports explicit `gpt-5.6-sol` and High reasoning but has no
  fast-mode selector. Child tasks will pass available settings and record fast mode unavailable/
  unverified. This coordinator task's launch settings are not exposed and cannot be verified.
- Live provider execution is not required for PR readiness unless separately approved.
- No unresolved choice changes the done condition. Exact schema field spellings may be frozen in
  the shared-contract commit without changing these semantic boundaries.

## Gate decision

PASS

The approved outcome has one observable human acceptance condition, authority and compatibility
boundaries are explicit, the private fixture and baseline are exact and evaluation-only, expected
files/tests and criterion evidence are mapped, and no unresolved decision requires invented scope.
Broad implementation may begin only after the native goal and lifecycle pointer are recorded and
the shared schema/failing-first contract is frozen.
