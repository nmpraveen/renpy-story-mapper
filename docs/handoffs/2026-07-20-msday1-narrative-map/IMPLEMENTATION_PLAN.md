# MsDay1 corrective Narrative Map implementation plan

Status: planning handoff only; no product implementation is authorized by this document.

Paste this entire document into one new Codex task. That task is the Phase Coordinator: it must
create and monitor the separate user-visible track tasks/worktrees defined below, not silently do
all track work in its own task.

Recommended milestone identity: **M15 - MsDay1 Narrative Map correction**. Do not use M14; M14 is
the unrelated deferred dynamic-adapter/runtime-tracing milestone. Do not reopen M13: its completed
contract deliberately forbids changing M11 membership, while this correction must replace that
membership. The phase coordinator must obtain approval and activate M15 through the repository
milestone workflow before changing product code.

## 1. Outcome

Replace the current micro-scene presentation with a readable Day 1 narrative graph whose visible
nodes are meaningful story events and whose lines come only from deterministic control-flow
authority.

The implemented flow must be:

```text
exact source and deterministic graph
  -> ordered narrative corridors with exact choices/rejoins
  -> bounded AI decisions about meaningful adjacent boundaries
  -> deterministic event membership
  -> independent event titles and summaries
  -> deterministic quotient graph over those events
  -> Story Map with nested temporary choices
  -> exact Detail/Evidence from every visible element
```

The first accepted result is deliberately limited to the private `MsDay1` fixture. Do not run a
full MsDenvers provider workflow until the Day 1 semantic and browser acceptance gates pass and the
user separately approves expansion.

## 2. Why this is a correction, not prompt polish

The final fixture produces 773 M01 nodes, 788 edges, six total menus, and four narrative menus. The
line-792 Day 1 baseline immediately before the final rejoin sentinel was added produced 165 M11
scenes, nine M11 temporary structures, and one chapter. Of its accepted boundaries, 115 came from
`minimum_narrative_run` and 35 from `unresolved_safety`. The sentinel changes one deterministic
node/edge, not the fragmentation diagnosis.

The defect begins before AI:

- M11 treats frequent visual-frame `scene` statements as human scene boundaries after only three
  narrative atoms.
- M11 titles then prefer visual or enclosing-label identifiers.
- M13 creates one job per already-broken M11 scene and is forbidden to regroup membership.
- The browser only replaces each M11 card's title/summary; it does not render M13's broader
  hierarchy as event nodes.

Therefore, do not attempt to fix this by increasing a threshold, rewriting only the prompt, or
displaying the current fixed-fan-in M13 segments. The correction must introduce a new event
membership and presentation projection.

## 3. Scope authority and invariants

### Immutable authority

- M10 remains authoritative for source selection, node/edge connectivity, choice ordering,
  conditions, effects, calls, returns, split/merge topology, terminals, unresolved behavior, and
  source evidence.
- M11 story atoms may be reused as ordered evidence-bearing presentation atoms.
- Current M11 scene boundaries, scene membership, titles, and presentation are inputs only for
  comparison; they are not authority for the new Narrative Map.
- AI may decide whether adjacent narrative corridor material belongs in the same human event and
  may write titles/summaries. AI may not add, delete, reorder, or redirect deterministic edges,
  choice arms, conditions, effects, or merge points.
- Every visible event, beat, choice, arm, and connector must retain exact M10/M11 provenance.

### Safety

- Never execute Ren'Py, game code, creator Python, screens, or runtime tracing.
- Never write into the original MsDenvers game folder or archive.
- Never commit or redistribute `MsDay1` source text.
- No cloud/provider call occurs without a fresh exact manifest and explicit user consent.
- The official walkthrough and `EXPECTED_NARRATIVE.md` are acceptance oracles only. They are never
  runtime prompt input or connectivity authority.

### Explicitly deferred

- Full-game MsDenvers processing.
- `How do I reach this?` route solving in the normal website journey.
- M14 dynamic adapters/runtime tracing.
- Installer, public distribution, media understanding, Q&A/chat, playthrough automation, and game
  editing.

### Exact private fixture scope

The private fixture preserves original reconstructed line numbers and bytes:

- lines 1-26: technical developer/patch/age setup, retained for structural fidelity but collapsed
  from the normal Story Map;
- lines 27-51: pre-Day-1 prologue framing, with the family introduction at lines 30-47;
- lines 52-54: exact Day 1 marker and opening screen action;
- lines 55-278: Terrance's disciplinary meeting;
- lines 280-332: Janet's phone call, office meeting, and Wanda's reaction;
- lines 334-430: family dinner;
- lines 431-789: Faye's concern/comfort sequence;
- lines 790-792: original trailing blank lines;
- line 793: the exact Day 2 scene statement retained only because it is the proven merge and
  extracted-scope sentinel for both final Faye choices. It is not Day 2 story content in this
  fixture.

The four narrative menu/rejoin pairs are line 143 -> 165, line 191 -> 233, line 623 -> 793, and
the nested line 674 -> 793. These are acceptance anchors, never production rules or prompt input.

## 4. Golden Day 1 acceptance shape

The Story Map must at minimum contain these separate chronological major event clusters:

```text
Prologue (separate and collapsible)
`-- Family and household introduction

Day 1
+-- Terrance's disciplinary meeting
|   +-- Fight with Max and breakup with Sandy
|   +-- Choice: confront or ignore his disrespect
|   |   +-- She tells him off.
|   |   `-- She ignores him
|   +-- Proven rejoin
|   +-- Wanda attempts an emotional breakthrough
|   +-- Choice: address or redirect his flirting
|   |   +-- She addresses his behavior
|   |   `-- She changes the subject
|   +-- Proven rejoin
|   +-- Review of Terrance's disciplinary history
|   +-- Wanda establishes twice-weekly counseling
|   `-- Wanda questions whether this is appropriate
|
+-- Janet calls Wanda to her office
|   `-- Pay-cut meeting and Wanda's reaction
|
+-- Family dinner
|
`-- Faye comforts Wanda
    +-- Choice: end the massage or keep going
    +-- Conditional choice: stop Faye or let her continue
    `-- Proven rejoin at the extracted Day 1 scope boundary
```

Additional useful sub-events are allowed only when they improve comprehension. The following are
release blockers:

- splitting Terrance's continuous office meeting into visual-frame scenes;
- combining the end of Terrance's meeting with Janet's meeting;
- showing developer, age-check, patch, notification, `Start`, `Clean`, module-end, or raw image
  identifiers as equal-weight story cards;
- flattening either temporary choice into a persistent route;
- losing an exact caption, ordered arm, proven rejoin, condition, effect, or source citation.

## 5. Target product surface

### Primary surface

The browser opens directly to **Story Map**.

- One chronological Day 1 band contains major event clusters.
- A cluster may contain linear story beats and compact choice diamonds in the same graph.
- Temporary arms fan out locally and visibly reconnect at the M10-proven rejoin.
- Persistent routes, when later introduced, use separate lanes; Day 1 temporary choices must not.
- Technical setup is one collapsed coverage corridor outside the default viewport.
- Clicking any cluster, beat, choice, arm, rejoin, requirement, or effect opens existing
  Detail/Evidence with exact reconstructed file/line provenance.
- The normal surface contains no separate legacy `AI Story Map`, `M07 Structure`, `Scenes`, or
  `Narrative` controls. Preserve compatibility code and place technical views behind an explicitly
  labelled advanced/diagnostic escape if required.

### Route solver retirement

Remove the visible `Reach this scene` panel and all `How do I reach this?` controls from the
website. Do not physically move or delete the M12 backend, persistence, stored results, API result
reader, or M13 M12-citation support.

Use **deferred / hidden from current product journey**, not `stale`, as the durable status. `Stale`
already means an exact authority mismatch and changing that meaning would create another bug.
Document the old UI and its restoration commit under `docs/deferred/M12_ROUTE_SOLVER_UI.md`.

The visible browser must make zero M12 solve/destination requests. Existing M13 citations with
`navigation.mode = "m12_result"` must still open their stored result through Detail/Evidence.

### Legacy AI surface retirement

The old M07/M08 `AI Story Map` is not the new Narrative Map. Remove its button and organization
controls from the normal journey while retaining storage/API compatibility and a safe legacy
fallback for older projects. Do not build the new map on `state.aiPage`.

## 6. New domain contracts

Freeze schemas before parallel implementation. Suggested names are descriptive, not binding until
semantic review passes.

### Narrative corridor

One deterministic, ordered, evidence-complete unit that may become part of a human event:

- stable corridor ID and schema/rule versions;
- lane, chapter/day, call occurrence, loop, and temporary-region context;
- ordered atom IDs and exact source order/locators;
- structural entry/exit node IDs and incident authoritative edge IDs;
- choice/rejoin ownership;
- hard boundary before/after and soft boundary signals;
- technical coverage attached but not promoted;
- exact authority binding and normalized hash.

### Boundary decision

One decision about a specific adjacent corridor boundary:

- exact left/right corridor IDs and boundary candidate ID;
- decision: `merge`, `split`, or `uncertain`;
- short evidence-grounded reason;
- confidence and warnings;
- provider/prompt/schema/input identity;
- no title, summary, membership list, or graph edge in this stage.

Hard topology boundaries are never submitted as merge candidates. An `uncertain` or unavailable
decision remains a visible conservative boundary and never destroys validated neighboring work.

### Narrative event

Python assembles this only after boundary decisions are validated:

- stable event ID derived from exact ordered corridor membership;
- ordered corridor/atom members with complete non-overlapping coverage;
- containing day/chapter, lane, occurrence, temporary-region, and loop context;
- entry/exit anchors and authoritative provenance;
- nested choice IDs and exact rejoin anchors;
- deterministic fallback title and coverage state;
- optional independently generated AI title/summary/claims.

### Narrative map

A deterministic quotient of M10 edges over accepted event membership:

- major event clusters and optional sub-event nodes;
- explicit choice, arm, rejoin, continuation, terminal, and unresolved presentation records;
- edges derived only from authoritative M10 relationships;
- gates/effects copied by ID from deterministic facts;
- hidden/collapsed technical coverage counts;
- stable layout order and bounded page/viewport data;
- exact Detail/Evidence navigation targets.

## 7. Pipeline design

### Stage A - Build deterministic corridors

1. Load exact current M10 authority and M11 story atoms.
2. Reconstruct source/control order per lane and call occurrence. Do not sort evidence by opaque
   hash when presenting chronology.
3. Collapse one-in/one-out technical nodes into provenance-bearing coverage.
4. Treat scene/show/hide/image changes as visual context signals only.
5. Cut only at authoritative hard structure: day/chapter progression, persistent-lane entry/merge,
   terminal, unresolved transfer that truly blocks continuity, call occurrence boundary, and
   temporary choice split/rejoin container boundary.
6. Preserve temporary branch arms as nested ordered corridor sets.
7. Emit soft candidates for changes in location, cast, narrative objective, resolved label/source
   transfer, or strong visual-family change. These are candidates, not automatic scenes.
8. Collapse the `label start:` developer/age/patch prefix as technical coverage and locate the
   first story-facing narrative anchor without deleting its evidence.

### Stage B - Decide meaningful boundaries

1. Prepare ordered windows that include exact story text, speaker, narration, source order,
   surrounding corridor summaries, and deterministic structural context.
2. Partition at hard boundaries and token limits. Use a small overlap halo for context, but assign
   each candidate boundary to exactly one job.
3. Ask only whether each soft candidate is a meaningful human event boundary. Do not ask for
   grouping, titles, summaries, claims, or edges at the same time.
4. Persist each decision independently with exact input identity. Cache/resume at the boundary-job
   level.
5. Validate known IDs, adjacency, scope, enum, bounds, and evidence handles. One repair may correct
   schema only; it may not reinterpret a different boundary.
6. Let Python assemble complete, contiguous event membership. Reject duplicate, missing, crossing,
   out-of-order, cross-lane, cross-occurrence, or cross-hard-boundary membership.

### Stage C - Summarize final events

1. Build one ordered evidence-complete prompt per final event after membership is frozen.
2. Request an action-focused story title, concise beginning-to-end summary, participating
   characters, and evidence-linked factual/interpretive claims.
3. Reject or fall back from titles such as `Start`, `Clean`, image IDs, module endings, labels,
   `Technical merge`, or `This scene defines...` when story-facing evidence exists.
4. Validate factual claims against direct owned evidence. Interpretation stays labelled.
5. Persist partial success per event. A failed title/summary must not remove deterministic event
   membership or neighboring accepted work.

### Stage D - Project and render the graph

1. Construct quotient edges locally from M10 edges crossing final event memberships.
2. Render major event clusters in chronological order.
3. Render temporary choices and exact arms/rejoins inside their containing cluster.
4. Attach requirements to entering arms and effects to the event/arm that causes them.
5. Keep technical coverage collapsed by default.
6. Preserve selection, pan, zoom, fit, search, and direct Detail/Evidence navigation.
7. Do not paginate a single coherent Day 1 narrative into arbitrary 30-node slices. Bound payloads
   through meaningful chapter/event clusters and explicit continuation only when genuinely needed.

## 8. Orchestration model

The implementation must use one user-visible phase coordinator and three separate user-visible
Codex tasks/worktrees. Internal worker agents may be used inside each task, but they do not replace
the separate tasks.

```text
Phase coordinator - contract, decisions, integration, evidence, PR
|
+-- Track A coordinator - deterministic corridors and event assembly
|   +-- corridor/model worker
|   +-- topology/provenance worker
|   `-- independent Track A reviewer
|
+-- Track B coordinator - AI boundary and event-summary workflow
|   +-- prompt/projection worker
|   +-- persistence/resume/validation worker
|   `-- independent Track B reviewer
|
+-- Track C coordinator - Story Map browser and legacy-surface retirement
|   +-- Narrative Map API/graph worker
|   +-- browser/layout/M12-M08 retirement worker
|   `-- independent Track C reviewer
|
`-- Final cross-track reviewer - exact integrated head, no edits
```

Every task must explicitly use `gpt-5.6-sol`, High reasoning, and fast mode disabled. If the task
creation surface cannot set or verify fast mode, record it as unavailable/unverified; do not claim
it was disabled.

### Coordinator responsibilities

- Establish the approved milestone contract and native goal before product changes.
- Record every visible task, worktree, branch, base, ownership boundary, and handoff in
  `TASKS.md`.
- Freeze shared schemas and exact acceptance fixtures before tracks diverge.
- Resolve architecture decisions; workers must not silently change the done condition.
- Integrate in the defined order, inspect actual diffs, and run cross-track checks.
- Obtain explicit consent before any Day 1 cloud/provider call.
- Keep the PR unmerged until the user approves it.

### Track A ownership

Expected primary area:

- new corridor/event/map domain modules;
- deterministic M10/M11 projection adapters;
- event membership, quotient-edge, and provenance tests;
- no provider, browser, M12, M07/M08, or CSS work.

Track A delivers the provider-free Day 1 event graph first. Track B and Track C code may compile
against frozen interfaces, but no final integration occurs until Track A's model passes review.

### Track B ownership

Expected primary area:

- new versioned boundary and event-summary prompts;
- ordered evidence projection with physical/reconstructed source order;
- boundary-job scheduling, cache, persistence, validation, repair, cancellation, and resume;
- no deterministic edge creation, event membership mutation outside the approved assembler, or UI
  implementation.

Track B first proves behavior with deterministic fake providers. A real Day 1 provider run is a
separate consented acceptance action after provider-free integration.

### Track C ownership

Expected primary area:

- Narrative Map API/presentation and browser graph;
- event clusters, temporary branch geometry, rejoin connectors, and evidence navigation;
- removal of the visible M12 route panel and old M07/M08 AI controls;
- compatibility guards for stored M12/M13 citations and older projects;
- packaged asset manifest and real-browser tests.

Track C does not delete M12/M07/M08 backends or invent graph structure in JavaScript.

### Integration order

1. Contract/schema freeze.
2. Track A provider-free corridor/event/map model.
3. Track B provider-independent interfaces and fake-provider workflow.
4. Track C API and browser against integrated Track A/B contracts.
5. Track A/B/C independent rereviews on rebased exact heads.
6. Final cross-track read-only review.
7. Provider-free Day 1 acceptance.
8. Explicitly consented bounded Day 1 live AI acceptance, if the user approves.
9. Windows/browser/package regression gates, evidence, PR preparation.

## 9. Phase plan

### Phase 0 - Contract and baseline

- Sync and verify clean tracked baseline while preserving unrelated untracked files.
- Record exact `MsDay1` source and archive hashes before access.
- Create the approved milestone contract, task ledger, semantic review, and native goal.
- Freeze the Day 1 expected structure as evaluation-only evidence.
- Record current baseline metrics and screenshots showing 165 scenes and technical `Start` noise.
- End semantic review with `PASS` or stop at `REVISE`; no broad code work before `PASS`.

### Phase 1 - Shared contracts and failing-first tests

- Add schema contracts for corridor, boundary decision, event, and narrative map.
- Add failing-first golden Day 1 tests for the two Terrance choices/rejoins and the Terrance-to-
  Janet boundary.
- Add synthetic tests for linear dialogue, frequent pose changes, local detours, nested choices,
  persistent branches, calls, loops, terminals, and unresolved transfers.
- Add retirement guards proving the normal website has no route solver or legacy AI organization
  controls.

### Phase 2 - Parallel Track A and Track B

- Track A builds deterministic corridors, event assembly, quotient topology, provenance, and
  provider-free fallback.
- Track B builds independent boundary decisions, ordered evidence projection, event summaries,
  durable caching/resume, and fake-provider tests.
- Each track receives an independent read-only review and bounded correction loop before handoff.

### Phase 3 - Track C browser integration

- Publish the Narrative Map API.
- Make Story Map the default and render the Day 1 event clusters/choices/rejoins.
- Remove M12 and old M07/M08 controls from the visible journey without deleting compatibility
  backends.
- Reclaim the route panel's width and verify 100%/200% layout.
- Preserve exact Detail/Evidence and old M13 M12-result citation navigation.

### Phase 4 - Integrated provider-free acceptance

- Rebase/integrate tracks on one candidate head.
- Run synthetic and exact `MsDay1` tests with a deterministic fake provider.
- Confirm the primary map matches the golden shape and contains no blocked technical titles.
- Confirm source, archive, M10 authority, and evidence hashes remain unchanged.
- Confirm opening/navigation performs zero provider calls and zero M12 solve requests.
- Obtain final cross-track review with no unresolved P0/P1/P2 narrative correctness finding.

### Phase 5 - Optional bounded live Day 1 acceptance

Only after explicit user consent:

- prepare one exact manifest for `MsDay1` only;
- show provider/model/settings, exact source scope, jobs, estimated calls/tokens, and limits;
- run boundary decisions and final event summaries;
- compare to the golden structure after the run, never include the golden answer in prompts;
- preserve validated partial work and perform a zero-call cache replay;
- do not expand to full MsDenvers.

### Phase 6 - Release evidence and handoff

- Run focused tests first, then required Windows/JavaScript/browser/package regression gates once
  the candidate is frozen.
- Record exact commands, counts, elapsed time, hashes, screenshots, review findings, and known
  limitations.
- Update master/project state only after semantic acceptance is real.
- Prepare one PR and leave it unmerged for user approval.

## 10. Required tests

### Exact Day 1 semantics

- Primary input hash is
  `14aa44ed95dec5402dfb02a1c4e01e63b3f3e329cf04fec37b04edebb5d588a6`.
- One `label start:` remains and the visible Day 1 anchor remains reconstructed line 52.
- Reconstructed line 793 remains only as the exact final rejoin/scope sentinel; line 794 and all
  later Day 2 story content are absent.
- Four narrative menu points retain exact line anchors 143, 191, 623, and 674.
- Terrance is one major cluster with two ordered temporary choices and two exact rejoins.
- Janet's phone call begins a separate event at reconstructed line 280; the first Janet image and
  dialogue begin at lines 283-284.
- Dinner begins a separate event at reconstructed line 334.
- Faye begins a separate event at reconstructed line 431.
- No story event crosses the line-793 extracted-scope boundary or presents the sentinel as Day 2
  story content.

### Structural correctness

- Frequent `scene`/show/hide/pose changes do not automatically create events.
- Temporary arms never escape their containing choice or duplicate post-rejoin continuation.
- Quotient edges preserve exact source/target event membership and M10 edge provenance.
- Calls, loops, persistent lanes, terminals, and unresolved transfers remain conservative.
- Every narrative atom is owned exactly once or explicitly technical/unresolved coverage.
- Every visible claim/effect/requirement reaches exact evidence.

### AI validation

- Boundary jobs cannot merge across hard structure or reference non-adjacent corridors.
- Invalid, missing, duplicated, crossing, or out-of-scope IDs fail independently.
- Cache/reopen/resume retries only missing or failed jobs.
- Event-summary failure preserves membership and deterministic fallback.
- Generic technical titles fail when story-facing evidence exists.
- No prompt or response grants edge, filesystem, web, tool, MCP, or application authority.

### Browser acceptance

- Initial viewport contains the Day 1 story spine and no technical boot cards.
- Terrance's cluster and both choices/rejoins are readable at 100% and 200%.
- Janet is visibly downstream and separate.
- Pan, zoom, fit, search, selection, and keyboard traversal work.
- Detail/Evidence opens exact source from every graph element.
- `routePanel`, `solveRoute`, `How do I reach this?`, old `AI Story Map`, and old organization
  controls are absent from the normal website.
- Selecting a node triggers no M12 solve and opening/navigation triggers no provider call.
- Existing M13 citations to stored M12 results still open correctly.
- No overflow, overlapping cards, severed connectors, or invented lines.

### Regression and safety

- M10/M11/M12/M13 authority and stored-result bytes are unchanged unless a versioned new Narrative
  Map payload is intentionally added.
- Existing projects without a new map open through a clearly labelled deterministic/legacy
  fallback and do not crash.
- No migration deletes old organization, route, narrative, or evidence records.
- Archive/source size, SHA-256, and timestamps are unchanged after access.
- Required pytest, Ruff, strict mypy, `pip check`, JavaScript syntax, asset-manifest, wheel/package,
  real-Chrome, and whitespace gates pass on Windows CPython 3.12.

## 11. Expected file areas

Exact filenames should be frozen during semantic review, but likely areas are:

- new `src/renpy_story_mapper/narrative_map/` domain, corridor, assembly, persistence, projection,
  service, and presentation modules;
- new versioned prompt/schema assets under `src/renpy_story_mapper/narrative/prompts/` or a new
  narrative-map prompt package;
- `src/renpy_story_mapper/web/api.py` and web contracts for the new map endpoints;
- `src/renpy_story_mapper/web/static/index.html`, `app.js`, `api.js`, `contract.js`, `graph.js`, and
  `styles.css` for the primary Story Map and retired controls;
- `docs/deferred/M12_ROUTE_SOLVER_UI.md` and a corresponding legacy M07/M08 surface note;
- focused synthetic, exact private Day 1, persistence, fault, UI, browser, and acceptance scripts.

Do not edit the private `MsDay1` source as part of implementation. Tests must read it only through
an opt-in private path or a sanitized synthetic fixture; private story text never enters Git.

## 12. Completion gate

The milestone is not complete because tests pass, AI jobs finish, hashes match, or reviewers find no
contract defect. It is complete only when a human can open the exact Day 1 result and immediately
understand the chronological story and divergences shown in Section 4.

Before PR readiness, the phase coordinator must present:

- the exact Day 1 Story Map at 100% and 200%;
- a text export of visible event/choice/rejoin order;
- direct evidence traversal for representative Terrance and Janet nodes;
- provider-free and, if authorized, live/replay metrics;
- source/archive immutability evidence;
- independent narrative-quality verdict against the golden acceptance target;
- all known limitations and the explicit statement that full MsDenvers remains unvalidated.

If Terrance is still fragmented, Janet is merged into Terrance, technical `Start` cards remain in
the initial story, or the map is merely renamed M11 scenes, the verdict is **REVISE**, regardless of
test count.
