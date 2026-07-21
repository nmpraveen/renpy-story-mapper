# M15.1 semantic review

Date: 2026-07-21

Correction base: `55ae57406cfb07a3c088d0dfd7c3b7e04ca9a719`

Prior result: CHANGES REQUESTED

Decision: PASS

## Review result

The prior provider-free result rendered a generic engineering graph rather than the requested
human-readable Story Map. Its completion claim, screenshots, visible-order export, reviews, and
Release evidence are rejected-baseline history. M15.1 remains inside M15, the existing integration
branch, and open PR #26.

The revised contract is semantically implementable. It replaces coarse corridor/event
presentation with fine story-facing units, exhaustive adjacent-gap boundary decisions,
deterministic hierarchical assembly, a separate frozen-membership summary stage, and a compact
normal-flow vertical interface. M10 remains the sole topology authority. AI is limited to bounded
classification and evidence-linked language; it cannot create membership, edges, choice order,
rejoins, gates, effects, or locators.

## Requirements mapping

| Requirement | Interpretation | Gate |
|---|---|---|
| Human-readable chronology | A non-technical reader can follow major story sections and their local choices without reading source mechanics | Frozen in `GOAL.md` criteria 7-8 and 14-17 |
| Fine semantic granularity | Each unit is one story-facing atom/turn; every legal adjacent gap receives one owned candidate | Frozen in criteria 1-5 |
| Deterministic authority | Python derives all membership and topology from validated decisions plus current M10/M11 facts | Frozen in criteria 4-6 and 9 |
| Temporary choices | Four local choices, eight exact arms, nested ownership, and proven rejoins remain explicit and ordered | Frozen in criteria 6, 14-15 |
| Two-stage live lifecycle | Boundaries and frozen summaries have separate previews, exact consents, jobs, caches, accounting, and publication | Frozen in criteria 7 and 10-13 |
| Honest failure semantics | Missing or invalid AI content is partial/failed, never silently replaced by generic completion text | Frozen in criteria 5 and 8-13 |
| Compact accessible UI | Normal-flow semantic HTML, bounded vertical column, local connectors, responsive 100%/200%, search/disclosure/keyboard | Frozen in criteria 15-17 |
| Exact evidence | Every visible interactive item opens its own matching Detail/Evidence identity and provenance | Frozen in criteria 9 and 17-18 |
| Privacy and immutability | Private inputs stay local, ignored, uncommitted, and unchanged; no game or creator execution | Frozen in criterion 19 and exclusions |
| Review and release | Separate exact-head track reviews, blind-then-oracle final review, user screenshot approval, one final Release and passing PR head | Frozen in criteria 18 and 20 |

## Architecture boundaries

- `src/renpy_story_mapper/narrative_map/` remains the M15 domain boundary. Versioned contracts must
  distinguish fine units, gap candidates, windows, decisions, beats, major clusters, local choices,
  summaries, build state, and live provenance.
- Track A owns provider-independent unit construction, candidate enumeration, validation,
  deterministic assembly, hierarchy, topology projection, and generalized fixtures. It cannot
  call a provider or depend on the private oracle.
- Track B owns provider projection, exact two-stage manifests and consent, jobs, cache, accounting,
  repair/validation, atomic publication, resume/retry, and zero-submit replay. It cannot create
  topology, layout, or private expectations.
- Track C owns production API/browser controls and a compact vertical presentation. It consumes
  validated server records and cannot infer or mutate story topology.
- Existing M10 authority, M11 evidence, M12 solver/storage, M13 stored-result citations, old-project
  compatibility, ingestion safety, loopback security, and atomic persistence are preserved.
- Private evaluation occurs only in the coordinator after generation freezes. The acceptance
  oracle and binding mockups are never provider input and never enter Git.

## Expected implementation and tests

| Area | Expected surfaces | Required focused evidence |
|---|---|---|
| Shared freeze | Narrative-map contracts, schemas, generalized examples, failing-first tests | Serialization/identity, exhaustive candidates, hard locks, hierarchy, provenance, two-stage state, density and UI contract failures |
| Track A | Contracts/adapters/assembly/projection/persistence helpers | Linear, split, nested choice, call, loop, lane, terminal, unresolved and fail-closed fixtures |
| Track B | Prompt/schema resources, service/workflow/persistence/provider adapters | Preview/consent identity, partial faults, repair, cancel/resume, reopen, cache/accounting, publication and zero-submit replay |
| Track C | Web contracts/routes/static HTML/JS/CSS and browser tests | Normal-flow layout, controls, 100%/200%, connector containment, keyboard/search/disclosure and exhaustive evidence mapping |
| Integration | Fake-provider end-to-end, compatibility, exact private working copy | Complete two-stage production, stable hashes, four choices/eight arms/rejoins, no authority mutation or private-input changes |
| Final acceptance | Real browser, independent review, Release/package and PR checks | Required captures, user approval, no P0-P2, exact passing pushed head on open unmerged PR #26 |

## Evidence plan

- Freeze shared schemas, generalized examples, and genuinely failing-first tests before track work.
- Create three separate visible Codex tasks/worktrees from that exact shared head and record task,
  worktree, branch, base, explicit model, explicit High reasoning, and unavailable fast selector.
- Require each track to commit a clean candidate and obtain an independent exact-head review before
  coordinator integration.
- Integrate in dependency order, inspect every diff, and run focused fake-provider and compatibility
  gates before any private live execution.
- Present the exact boundary manifest and await explicit consent. After boundaries freeze, present
  a different exact summary manifest and await a second explicit consent.
- Freeze the live candidate before oracle/mockup comparison; require a separate final reviewer to
  perform a source-first review and then compare that same candidate against private references.
- Run real Chrome at 100% and 200%; present actual final-head screenshots for explicit user visual
  approval; then run one final Windows Release/package gate and verify the pushed PR head.

## Assumptions and resolved conflicts

- The native goal service currently reports no active goal even though the prior lifecycle record
  names the completed original M15 goal. The user explicitly requested a start, so the coordinator
  will create one replacement M15 goal after this contract is recorded; there will still be exactly
  one active milestone goal.
- The handoff requests Medium reasoning for worker tasks, while the current repository dispatch
  policy requires `gpt-5.6-sol` with High reasoning for every current milestone task. The newer
  repository policy controls task dispatch. The live product acceptance profile remains the
  contractually requested `gpt-5.6-sol`, Medium reasoning, fast mode off.
- The visible task-creation surface exposes model and thinking controls but no fast-mode selector.
  Fast mode will be recorded unavailable/unverified, never falsely claimed disabled.
- The correction handoff and private evaluation materials are locally ignored. They may guide the
  coordinator's post-generation acceptance but cannot be copied into tracked artifacts, worker
  prompts, provider input, or product hardcoding.
- The exact source and archive fingerprints match their private manifest at correction start. Final
  before/after proof remains required.
- Two separate live consents and later user screenshot approval are mandatory acceptance gates;
  neither is inferred from the user's authorization to start implementation.

## Gate decision

The observable done condition, authority split, privacy boundary, lifecycle correction, expected
implementation surfaces, tests, evidence, and task ownership are explicit. No unresolved semantic
choice requires invented product scope. Broad implementation may begin after the replacement native
goal is recorded and the shared schema/example/failing-first freeze is committed.

PASS
