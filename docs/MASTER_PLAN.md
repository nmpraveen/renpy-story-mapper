# Ren'Py Story Mapper - Windows Master Plan

Last revised: 2026-07-16

Status: M01 through M12 are complete and merged. M13 was explicitly approved on 2026-07-16 and
retains its semantic-review `PASS`. Existing unmerged PR #23 returned to `Integration` on
2026-07-17 after a final bounded current-head audit reproduced P1 defects in restart, accounting,
privacy, and citation behavior. The two bounded tracks integrated at `9ab1dbd`, but final review of
lifecycle head `532eefc` found one remaining P1: a recovered unresolved reservation consumes usage
without consuming the per-job total-attempt ceiling. The explicitly authorized additional
correction at `a7e242b` closes the single-reservation case, but its independent rereview found that
multiple durable reservations for the same historically reused attempt are collapsed to one
history slot and can still bypass the ceiling. M13 remains in `Verification` and PR #23 is not
currently ready. Prior review, live/replay, and Release results remain historical evidence for
their exact heads; they are not proof of the pending corrected head.

## 1. Product goal

Build a private Windows application that accepts a Ren'Py game folder or `scripts.rpa` archive and
turns the story into a readable, interactive flowchart.

The application is for understanding complicated branching stories. It is not a chatbot, a game
editor, or a public distribution project. The main experience is:

```text
Select a Ren'Py game
  -> analyze it without running game code
  -> identify story paths, choices, requirements, and state changes
  -> classify temporary detours, persistent routes, loops, merges, and endings
  -> explore a broad route map and its exact detail/evidence workspace
```

The final map must answer visually, without requiring the user to ask questions:

- What are the major story arcs and outcomes?
- Which choices cause the story to branch?
- What conditions or points are required to enter a path?
- What changes after an event, such as love, lust, skill, money, job, or story flags?
- Where do paths merge, loop, call shared material, or end?
- What dialogue and source lines prove each result?

This document is the permanent source of truth for all further project tasks. If another document,
old infographic, task brief, or prior conversation conflicts with this plan, this plan wins.

## 2. Current foundation and what we learned

### M01 - Analyzer foundation

Status: Complete and merged through PR #1. M01 documentation was merged through PR #2.

M01 safely reads RPA archives, prefers `.rpy` over matching `.rpyc`, parses a conservative Ren'Py
subset, and builds a source-linked control-flow graph containing labels, choices, conditions,
jumps, calls, returns, fallthrough, and unresolved behavior.

### M02 - Deterministic semantic projection

Status: Complete and merged to `main` through corrective PR #4 on 2026-07-10. PR #3 was originally
merged into the already-merged documentation branch, so PR #4 placed the M02 implementation onto
`main`.

M02 converts the low-level graph into label-based scenes, narrative beats, structural beats, and
normalized transitions. It is a reliable intermediate representation, not the final human-facing
story map.

### Canonical-sample findings that drive the remaining plan

The canonical scoped M02 run produced:

- 11 label-based scenes
- 422 beats
- 532 transitions
- 206 opaque or technical beats
- 64 narrative beats
- 28 condition beats
- 2 choice beats containing 6 displayed choices
- 24 unresolved semantic records

The `new_prologue` label alone became one scene containing 196 beats: 62 narrative, 49 opaque,
8 condition, and 2 choice beats. Rendering only labels would hide most of the story inside one
giant node. Rendering all 422 beats would create an unreadable wall of technical nodes and edges.

The sample also proves that state matters to story comprehension. Examples include:

- choice gates such as `ian_wits > 0` and `ian_charisma > 0`
- progression gates such as `chapter == 0`
- stat-related calls such as `call xp_up('lust')`
- numeric changes such as `ian_lena_mmf_points += 1`
- relationship and route flags such as `ian_lena_dating`, `ian_cheating`, and
  `ian_louise_love`
- story progression assignments such as `chapter = 3`

Therefore, labels cannot be treated as final scenes, technical statements cannot simply be drawn
as equal-sized nodes, and choices cannot be understood without showing their requirements and
effects.

## 3. Non-negotiable product rules

1. The game folder and original archive are always read-only.
2. Never execute embedded Ren'Py, screen, creator-defined, or game Python code.
3. Deterministic analysis owns source selection, labels, choices, conditions, jumps, calls,
   returns, fallthrough, merges, loops, endings, and graph edges.
4. Deterministic analysis also owns any stat requirement or state change that can be read safely
   from explicit syntax. AI may explain it but may not invent it.
5. Prefer `.rpy` when matching `.rpy` and `.rpyc` files both exist.
6. Every structural fact, gate, effect, and detailed story item retains source-file and physical
   line evidence.
7. Dynamic or unsupported behavior is visibly marked unresolved rather than guessed.
8. AI is used to organize and describe story meaning, not to decide factual connectivity.
9. Story text is never sent to a cloud AI provider without explicit user enablement.
10. The deterministic map remains available when AI is disabled or unavailable, although it may
    be less polished.
11. Windows with CPython 3.12 is the only runtime authority.
12. Work on exactly one explicitly approved milestone at a time.

## 4. The two-level story map

The current three-level arc/event/evidence hierarchy is superseded. The product has exactly two
user-visible levels; internal beats and AI events may remain implementation records but do not
create extra navigation levels.

### Level 1 - Route Map

Purpose: understand the story spine, meaningful choices, persistent routes, merges, loops, and
endings at a glance.

- Default to a chronological chapter/day/major-event spine.
- Draw temporary choices as compact detours that visibly reconnect at proven merge points.
- Draw persistent mutually exclusive routes in separate lanes until a proven merge or terminal.
- Put requirements on entering edges and effects on the event or path that causes them.
- Distinguish game endings, route endings, dead ends, update boundaries, and unresolved targets.
- Collapse routine dialogue and technical one-in/one-out chains into corridors or coverage markers.
- Never turn individual technical fallback beats into thousands of equal-weight cards.
- Keep the initial viewport near 30 meaningful nodes, with compact nodes and visible connecting
  lines as the primary visual grammar.

### Level 2 - Detail and Evidence

Purpose: inspect and verify the selected milestone, choice, edge, gate, merge, loop, or ending.

- Show the concise summary and immediate predecessor/successor context.
- Show exact choice captions, conditions, requirements, effects, dialogue, and narration.
- Retain relative source path and qualified physical/reconstructed line evidence.
- Pair every AI claim directly with deterministic evidence IDs and label interpretation as such.
- Provide a small local path strip, not another full graph level.
- Use **Back to Route Map** as the only level transition.

Required interaction remains pan, zoom, fit, search, filters, technical/unresolved toggles,
selection preservation, and direct evidence traversal. Physical zoom may change visual density but
must never create an additional semantic level.

## 5. Story state, requirements, and effects

Story state must be a first-class part of the graph rather than text hidden in a source inspector.

### State categories

The model must support, without assuming a game's exact naming convention:

- affection, love, lust, friendship, and relationship points
- skills and personality statistics
- money, inventory, and resources
- jobs, roles, locations, and memberships
- route, dating, cheating, allegiance, and event flags
- chapter, day, time, and other progression markers
- creator-specific variables whose meaning is initially unknown

### Deterministic state extraction

Safely recognize simple explicit constructs without executing them, including:

- requirements: comparisons and boolean conditions on choices or branches
- effects: direct assignments, `+=`, `-=`, and safe literal changes
- relevant calls whose target and literal arguments are visible
- state changes inside each choice branch

For every extracted item, retain the original expression and source evidence. A normalized human
label such as "Lust +1" may be added, but the exact source remains authoritative.

Complex Python, computed variable names, unknown functions, and effects that depend on runtime
execution remain unresolved. The application must say "possible or unresolved effect" rather
than present them as proven facts.

### Map presentation

- Requirements appear on the path entering an event or choice outcome.
- Effects appear on the event or path that causes them.
- Numeric deltas use compact badges such as `Love +1` or `Money -10`.
- Boolean or categorical changes use badges such as `Dating = true` or `Job = Company Z`.
- Important changes may be promoted to Levels 1 or 2; all extracted changes remain available at
  Level 3.
- The same underlying variable may have a user-editable display name and category.

## 6. Technical architecture

```text
Game folder, .rpy, .rpyc, or .rpa
        |
Read-only inventory, source precedence, and isolated compiled-source recovery (M06)
        |
Safe static parser
        |
Authoritative source-linked control-flow graph (M01)
        |
Deterministic scenes, beats, and transitions (M02)
        |
Requirements, state effects, and durable project storage (M03)
        |
AI-assisted event grouping, titles, summaries, and high-level meaning (M05)
        |
Deterministic control regions and route semantics (M06)
        |
Two-level route map plus resumable parallel AI enrichment (M07)
```

The underlying structure is a graph, not necessarily a tree. The interface may present a clean
flowchart, but it must preserve splits, merges, loops, calls, returns, shared scenes, and endings.

### Core records

- Project and source-file fingerprint
- Source file and physical span
- Label, beat, and deterministic scene
- Human-facing event and story arc
- Character
- Choice and choice outcome
- Requirement or gate
- State variable, category, and display name
- Proven effect or unresolved possible effect
- Typed graph edge
- Ending and unresolved behavior
- AI interpretation with provider, model, prompt version, input hash, confidence, and evidence IDs
- User correction or override

### Planned local stack

- Python 3.12 and the existing analyzer package
- SQLite for projects, graph data, state facts, AI cache, and user corrections
- A loopback-only local Python web service and browser interface are the primary shell from M06.5.
  Analysis, projects, source access, AI execution, and all sensitive data remain on the Windows
  machine; the browser is a presentation client, not a hosted service.
- The loopback browser interface is the sole supported product surface from M08. A narrowly scoped
  native Windows file/folder dialog helper may remain behind the local service, but the legacy M04
  `QGraphicsView` application, entry point, assets, tests, and documentation are removed.
- One minimal provider-neutral AI interface with only the provider adapter needed for the first
  working version; multiple provider integrations are not a milestone requirement

PyInstaller packaging, an installer, public distribution, macOS support, game editing, and game
patching are outside the active plan.

## 7. Milestones

M01 through M09 are complete. The user approved a post-M05 redesign on 2026-07-12 after a
compiled-only large-game trial exposed source-recovery, branch-classification, AI-scale, and graph
readability limits. On 2026-07-13 the user approved M08 to make the product browser-only and to
validate AI as the required human-readable story stage.

### M03 - Story state and durable projects

Status: Complete and merged to `main` through PR #5 on 2026-07-10.

Objective: preserve analyses in a reusable project and add deterministic requirements/effects so
the later visual map can explain why routes open and what choices change.

Deliverables:

- Versioned SQLite project schema and tested migrations.
- Storage for sources, M01 graph, M02 semantic data, diagnostics, unresolved records, and metadata.
- Project create, open, refresh, and delete operations.
- Content-hash-based incremental reanalysis so unchanged sources are not reparsed.
- Deterministic extraction of simple branch and choice requirements.
- Deterministic extraction of simple assignments, increments, decrements, and literal-argument
  state-related calls.
- State-variable registry with inferred category, original name, editable display name, and source
  evidence.
- Explicit distinction between proven effects, possible effects, and unresolved effects.
- Safe temporary-file, cancellation, corruption, and recovery behavior.
- Representative fixtures for love/lust points, relationship flags, skills, money, jobs, chapter
  gates, chained requirements, and dynamic unsupported cases.

Acceptance criteria:

- Closing and reopening a project preserves byte-equivalent authoritative graph, semantic, gate,
  and effect data.
- Refreshing an unchanged project does not reparse unchanged sources.
- A changed source invalidates only its dependent data.
- Simple examples such as `love += 1`, `dating = True`, `job = "Company Z"`, and
  `wits > 0` are stored with exact source evidence and correct proven/unknown status.
- The canonical sample visibly captures gates including `ian_wits > 0` and
  `ian_charisma > 0`, plus representative point or flag changes such as
  `ian_lena_mmf_points += 1`, without executing the game.
- Dynamic or unsafe expressions remain unresolved and are never presented as proven effects.
- The full canonical archive can be analyzed into a project without writing beside it; elapsed
  time and peak-scale counts are recorded even if later UI work still needs progressive loading.
- Database corruption and incompatible versions fail safely.
- Pytest, Ruff, strict mypy, and `pip check` pass on Windows.

Explicit exclusions:

- No desktop UI beyond a minimal test or diagnostic harness.
- No AI scene grouping.
- No packaging or installer work.

Completion evidence:

- Versioned SQLite schema v2, migrations, structural validation, atomic lifecycle operations,
  source fingerprints, parsed-module cache, dependency-scoped invalidation, and durable user state
  metadata are implemented.
- Deterministic requirements and state effects retain exact physical-line evidence and distinguish
  proven, possible, and unresolved behavior without executing game code.
- The full canonical archive produced a 715,141,120-byte project containing 405,449 graph nodes,
  462,767 edges, 2,652 scenes, 252,061 beats, 38,977 requirements, and 55,356 proven/possible
  effects. Initial creation completed in 334.183 seconds after the full-graph traversal fix.
- An unchanged canonical refresh parsed 0 sources, reused all 77 selected `.rpy` sources in 0.655
  seconds, and left both the project and archive byte-identical.
- Windows CPython 3.12 acceptance passed 93 tests, Ruff, strict mypy, and `pip check`; independent
  review found no remaining P0-P3 issues.

### M04 - Three-level Windows story map

Status: Complete and merged to `main` through PR #6 on 2026-07-11.

Objective: build the actual Windows application and prove that a complicated game can be explored
without displaying hundreds of equal-weight nodes at once.

Deliverables:

- PySide6 desktop shell with game/archive selection and project create/open/refresh.
- Responsive background analysis with progress, cancellation, and clear errors.
- Interactive graph canvas with pan, zoom, fit, selection, and stable navigation.
- Three semantic detail levels as defined in Section 4.
- Deterministic hierarchy for the pre-AI map: labels or chapters -> structural event groups ->
  exact beats and source evidence.
- Progressive expansion and virtualization so only visible or requested details are rendered.
- Distinct visual language for story events, choices, gates, effects, merges, loops, shared calls,
  endings, technical material, and unresolved behavior.
- Requirement and effect badges with filters by variable/category.
- Search and source-evidence inspector.
- User controls to rename variables, categorize state, rename nodes, hide technical noise, and
  preserve those corrections.
- Diagnostics/log panel suitable for troubleshooting without exposing the original game content
  unnecessarily.

Acceptance criteria:

- A user can select the canonical archive, create or reopen its project, and reach a usable map
  without command-line work.
- Opening the canonical project does not attempt to render all beats or edges simultaneously.
- The M02 `new_prologue` result is presented as an expandable container, not one unreadable
  196-beat card and not a 196-node default view.
- Zooming changes the amount and meaning of displayed information, not only its physical size.
- Choices visibly show their options, requirements, and known effects.
- Selecting any overview or event item can reveal Level 3 source evidence.
- Large branches can be expanded independently and collapsed without losing the user's place.
- The UI remains responsive and cancellation leaves the saved project consistent.
- No operation writes to the game directory or executes game code.
- Windows UI tests plus pytest, Ruff, strict mypy, and `pip check` pass.

Explicit exclusions:

- Do not pretend deterministic labels are final human-quality story scenes.
- No chatbot, natural-language question interface, ending finder, or route-question workflow.
- No packaging or public release work.

Completion evidence:

- The PySide6 shell, cancellable background project lifecycle, native virtualized canvas, bounded
  schema-v3 presentation index, three semantic levels, search, evidence inspector, filters, and
  durable node/state overrides are integrated.
- The copied canonical project built its first presentation index in 136.324 seconds and reopened
  to a bounded overview in 2.457 seconds. Its row-oriented index contains 318,980 presentation
  nodes, 432,438 presentation edges, 252,061 evidence rows, 94,333 gate/effect facts, and 789,446
  search rows.
- The canonical Windows Qt workflow reached an 80-node/120-edge overview (200 rendered items under
  the 240-item hard cap), focused off-page `new_prologue`, rendered its 49 structural event groups,
  displayed choice requirements/effects, and descended to a three-node exact-evidence slice.
- Required facts remained exact and proven: `ian_wits > 0` at `scripts/script.rpy:244`,
  `ian_charisma > 0` at line 246, `ian_lena_mmf_points += 1` at
  `scripts/master_script.rpy:2256`, `ian_lena_dating = True` at
  `scripts/gallery/gallery_scene_setups.rpy:1103`, and `chapter = 3` at
  `scripts/master_script.rpy:1994`.
- Windows CPython 3.12 acceptance passed 133 tests, 11 focused M04 contracts, Ruff, strict mypy,
  and `pip check`; independent review found no remaining P0-P3 issues.
- The canonical archive remained byte- and timestamp-identical: SHA-256
  `953fae213f32a9d0cae2432ef09924d2f9f83c960691f42a15b73cc747aade99`, 70,031,252 bytes,
  `2026-07-10T17:11:44.0000000Z` before and after.

### M05 - AI-Organized Story Explorer and Final Product Validation

Status: Complete. The user merged implementation PR #7 to `main` at `2df4d67` on 2026-07-11.
Final acceptance evidence and closeout artifacts were completed immediately afterward. M05 is the
final milestone in the approved roadmap.

Objective: convert the technically correct M04 graph into the finished story-reading experience.
The default journey must become an arc-first Story Explorer while M01-M04 remain the immutable
factual foundation for connectivity, requirements, effects, evidence, and source locations.

#### Locked product decisions

- The default experience is an arc-first Story Explorer in a polished adaptive Windows light/dark
  interface.
- AI runs only after a manual **Organize Story** action.
- One provider-neutral boundary has one active `CodexCliProvider` mode for M05: cloud organization
  through the user's existing ChatGPT/Codex login. The dormant LM Studio adapter may remain in the
  codebase, but it is hidden from the M05 user journey and its product validation is deferred.
- Every cloud run requires a fresh explicit confirmation before rich story evidence is sent.
- Every M05 cloud organization request explicitly selects GPT-5.6 Luna (`gpt-5.6-luna`) with High
  reasoning and fast mode disabled. There is no automatic model fallback or user override in the
  accepted M05 path. The locked CLI model argument is recorded as authoritative; if the CLI emits
  model metadata it must match, while an unavailable selection fails at process execution. Record
  the requested model, any reported identifier, and the reasoning profile.
- A successful run creates a reviewable draft; it never silently replaces the accepted map.
- Corrections include rename, split, merge, move, hide, pin, approve, and reject.
- The generated complex branching fixture is the primary M05 AI acceptance source. The small real
  `script small new.rpy` file is a secondary read-only smoke source after separate per-run cloud
  consent. Full canonical-game AI organization and LM Studio product validation are deferred and
  must not be claimed as M05 acceptance evidence.
- Existing base-project compaction is deferred. M05 measures database growth but does not gate on
  reducing the approximately 2.26 GB project.

#### Welcome and project opening

- Replace the empty canvas with a welcome screen containing recent projects, source type,
  last-opened time, organization status, and deterministic/AI badges.
- Provide primary actions for **Open Game Folder**, **Open Archive**, and **Open Project**, plus a
  concise static-analysis safety statement.
- Present progress as a clear task with stage, percentage, elapsed time, and Cancel.
- Show errors contextually with a recovery action. Move raw diagnostics under
  **Help -> Diagnostics**.
- Opening an accepted organized project immediately shows its accepted story map without rerunning
  deterministic analysis or AI.

#### Arc-first workspace

Use one consistent three-pane workspace:

- Left, approximately 280 px: project navigator with Overview, major arcs, characters, outcomes,
  and saved filters.
- Center: focused semantic map using the remaining width.
- Right, approximately 360 px: contextual inspector with Summary, Choices & State, Evidence, and
  Details tabs.
- Top command bar: project name, breadcrumb, search, filters, Organize Story, and compact project
  actions.
- Bottom status strip: current level, visible-item count, organization provenance, and background
  status.

Persistent override forms become contextual Edit actions; variable/category filters move into a
filter popover; technical and unresolved toggles move into View options; diagnostics stay closed
unless an error occurs; raw labels remain available as evidence metadata rather than default titles.

#### Semantic levels, rendering, and layout

- Level 1 - Arcs: show no more than 12 accepted arcs or turning points by default in chronological
  order. Each card includes a title, one-sentence summary, involved characters, major
  requirements/effects, outcomes, and evidence coverage.
- Level 2 - Events: show the selected arc as a deterministic layered branch map with no more than
  30 event cards in the default slice. Choices open route lanes; merges, calls, loops, and endings
  retain distinct styles.
- Level 3 - Evidence: show dialogue, narration, choices, expressions, facts, relative paths, and
  physical lines as a readable evidence timeline rather than another equal-weight graph.
- Mouse-wheel semantic zoom and explicit level controls remain synchronized.
- The existing 240-rendered-item cap remains an absolute safety boundary.
- With AI disabled or unavailable, the same workspace uses deterministic labels and structural
  groups and visibly identifies them as **Technical organization**.
- Layout remains deterministic: collapse strongly connected components, assign ranks from
  authoritative edges, order nodes with stable crossing-reduction passes, and route branches into
  lanes. AI never supplies coordinates or edges.

#### Visual and accessibility system

- Follow Windows light/dark palette changes at runtime.
- Use Segoe UI or system typography with 12 px metadata, 14 px body, 18 px section titles, and
  24 px project/arc titles.
- Use restrained semantic colors: cyan for flow, violet for choices, amber for requirements, green
  for effects, red for unresolved behavior, and neutral system colors elsewhere.
- Use icons with labels and never communicate state through color alone.
- Give every interactive control an accessible name and visible keyboard focus state.
- Support keyboard traversal through arcs, event cards, inspector tabs, and evidence records.
- Preserve usability under Windows display scaling and 200% application zoom.

#### Provider interface and process boundary

Introduce this provider-neutral protocol:

```text
OrganizationProvider.status() -> ProviderStatus
OrganizationProvider.organize(request, progress, cancelled)
    -> OrganizationChunkResult
OrganizationProvider.cancel()
```

Use `CodexCliProvider` in `CODEX_CHATGPT` mode for the accepted M05 path. Cloud mode reuses `codex
login` without reading or copying OAuth credentials. The existing `CODEX_LMSTUDIO` adapter remains
dormant and is not exposed by the M05 UI. Every run launches `codex exec` through `QProcess`
directly, never a shell, in a sterile temporary working directory with the equivalent of:

```text
codex exec
  --ephemeral
  --skip-git-repo-check
  --sandbox read-only
  --ignore-user-config
  --ignore-rules
  --strict-config
  --disable fast_mode
  -c model_reasoning_effort="high"
  --model gpt-5.6-luna
  --json
  --output-schema <packaged-schema>
  -
```

The provider must invoke `--model gpt-5.6-luna`; any model identifier emitted by structured run
metadata must match. An unavailable model, unsupported High-reasoning profile, or conflicting
reported model rejects the run without changing the accepted organization. Codex CLI 0.144 may
omit redundant model metadata on success, so the locked command argument remains the recorded
authority. It must never fall back to the authenticated default model. LM Studio's
`--oss --local-provider lmstudio` path is deferred and unavailable from the M05 interface.

- Stream story input through standard input; do not write prompt files.
- Do not enable web search.
- Treat command execution, file modification, MCP calls, or web-search JSONL events as policy
  violations: terminate and reject the run.
- Cancellation terminates the process, waits up to two seconds, kills it if needed, removes
  temporary material, and leaves accepted organization unchanged.
- `--ephemeral` prevents Codex rollout persistence.
- Store normalized structured output, hashes, timings, usage counts, CLI version, provider mode,
  and model identifier when available, but never credentials or raw provider logs.
- Missing Codex, signed-out cloud mode, unavailable GPT-5.6 Luna/High profile, model mismatch,
  invalid JSON, refusal, timeout, rate limiting, policy violation, and cancellation return
  sanitized actionable errors.

#### Deterministic input and chunking

Construct input only from M01-M04 records: scope ID; ordered beat IDs; beat kinds and speakers;
dialogue, narration, and choice captions; conditions and explicit source expressions; proven or
possible fact IDs and normalized values; relative path and physical span; and authoritative local
adjacency between included beats.

- Partition first by deterministic scene/label, then at choices, jumps, returns, and strong
  condition boundaries.
- Target at most 48,000 characters and 120 beat records per request.
- Include up to two neighboring narrative beats as context, but never assign an overlapping beat to
  two accepted events.
- Omit routine technical commands from provider text while retaining their collapsed deterministic
  transitions.
- Stage 1 groups beats into human events.
- Stage 2 reconciles neighboring event candidates inside each deterministic scene.
- Stage 3 receives event summaries, major facts, characters, and locally derived connectivity, not
  full dialogue, and groups events into arcs.

#### Structured output and validation

The provider may return only event/arc titles and concise summaries; existing member beat/event
IDs; evidence-supported character names; `supporting`, `major`, or `turning point` importance;
outcome descriptions; existing fact IDs worth promoting; existing evidence IDs supporting each
interpretation; warnings; and ungrouped IDs.

It must not return new authoritative graph edges, conditions, state changes, source locations, or
route destinations. Validate that:

- every referenced ID exists in the exact request;
- every narrative, choice, and condition beat is assigned exactly once or explicitly ungrouped;
- technical beats may remain collapsed;
- event membership preserves deterministic order;
- titles contain at most 80 characters and summaries at most 320 characters;
- promoted facts match existing M03 fact IDs;
- every interpretive claim has evidence IDs; and
- unknown IDs, invented facts, duplicate membership, illegal crossings, missing required coverage,
  or malformed output reject the chunk.

Allow one schema-repair retry. A second failure leaves the scope deterministic. Derive event and arc
edges locally as quotient graphs over authoritative M01/M02 transitions, and attach requirements
and effects locally from M03 facts rather than model prose.

#### Schema v4, cache, and durable state

Add normalized storage for:

- `organization_runs`: mode, model/profile, prompt/schema versions, generation, status, timings,
  usage, and sanitized failure;
- `organization_chunks`: scope, input hash, cache state, and normalized result hash;
- `organization_drafts`: validated candidate payloads awaiting review;
- `story_arcs` and `story_events`: accepted titles, summaries, order, origin, and pinned state;
- `story_event_members` and `story_arc_members`: authoritative membership mappings;
- `story_event_edges`: locally derived connectivity with deterministic provenance;
- `story_claims` and `story_claim_evidence`: interpretation/evidence distinction;
- `story_edits`: durable rename, split, merge, move, hide, pin, approve, and reject operations; and
- `organization_cache`: provider mode, model fingerprint, prompt version, schema version, and input
  hash.

Migrate transactionally and backward-safely; cancellation or failure preserves the schema-v3
project. Reuse cached results only when content, ordered IDs, provider mode, model profile, prompt
version, and schema version all match. Refresh invalidates only changed chunks and affected
reconciliation scopes. Accepted user edits and pinned groupings override later AI results. If a
refresh removes a referenced beat, retain the edit as **Needs review**. Do not duplicate raw dialogue
in enrichment tables; reconstruct provider input from authoritative payloads. Record the M05
database-size delta without making compaction an acceptance gate.

#### Review and corrections

A successful run creates a draft. The review workspace compares current accepted organization with
proposed arcs/events and shows added, removed, renamed, split, merged, and ungrouped content;
evidence coverage and rejected/fallback scopes; provider mode, model/profile, prompt version, cache
reuse, elapsed time, and local/cloud status.

- **Apply Draft** promotes the entire validated draft atomically.
- **Discard Draft** removes it without changing the accepted map.
- Rename arcs/events inline.
- Split only at a deterministic beat boundary.
- Merge only contiguous events in the same arc.
- Move events between arcs without changing authoritative event edges.
- Hide presentation noise and pin user-edited groups against later replacement.
- Reject individual candidate groups and retain their deterministic fallback.

#### Worker sequence and ownership

Create user-visible Windows worktree tasks from the milestone base:

1. `codex/m05-story-model`: schema v4, migrations, organization records, quotient graphs,
   corrections, and caching; storage/story-domain modules and tests only; no provider or UI code.
2. `codex/m05-codex-organizer`: Codex discovery, the consent-gated ChatGPT path, chunking, schemas,
   validation, cancellation, and sanitized errors; provider package and mocked process tests only;
   no UI or storage migrations. The accepted configuration is GPT-5.6 Luna with High reasoning and
   fast mode disabled; the existing LM Studio adapter is dormant and deferred.
3. `codex/m05-layout-and-fixtures`: deterministic layered layout, branch lanes, semantic styles,
   and representative story/evaluation fixtures; canvas/layout and new fixtures only.
4. `codex/m05-story-explorer-ui`: welcome screen, arc-first workspace, review flow, inspector,
   corrections, adaptive theme, accessibility, screenshots, and UI tests; begin after shared model
   and provider contracts are integrated; no provider or storage implementation.
5. `codex/m05-independent-review`: final adversarial review and new review tests only; production
   edits excluded.

Integrate story-model and provider contracts first, then layout, then UI. Return defective work to
its responsible task. Worker completion alone is not acceptance.

#### Windows verification and acceptance

Run with Windows CPython 3.12:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m mypy src\renpy_story_mapper
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Milestone tests cover schema-v3-to-v4 migration, cancellation, corruption, rollback, quotient-graph
derivation, output validation, invented IDs/facts, chunk boundaries and overlap, coverage,
reconciliation, cache keys, mocked Codex success/refusal/malformed/rate-limit/policy-violation/
timeout/cancellation/missing-executable behavior, the active ChatGPT command profile, isolation of
the dormant LM Studio adapter, consent before every cloud run, absence of implicit cloud calls,
atomic draft apply/discard, the full correction workflow,
adaptive theme, keyboard/focus/accessibility/scaling/evidence traversal, deterministic fallback,
accepted-project opening without provider calls, and cached reruns with zero provider subprocesses.

Validate the real Codex/ChatGPT path first on the generated complex branching fixture through the
existing login and structured-output path. The command must explicitly select `gpt-5.6-luna`, High
reasoning, and disabled fast mode; the command selection and any reported metadata must match.
After a separate
fresh confirmation, use `script small new.rpy` as a secondary read-only real-script smoke run.
Do not use the compiled-only `script smaller version.rpyc`, because M05 does not add decompilation.
LM Studio and full canonical-game AI organization are deferred rather than silently substituted.

Before and after every canonical access, record SHA-256, size, and `LastWriteTimeUtc`. Acceptance
requires:

- The complex fixture's Level 1 shows no more than 12 coherent arcs or turning points.
- The complex fixture forms approximately 12-30 coherent events while preserving its four endings,
  27 choices, 26 proven gates, 88 effects, loop, merge, and shared call/return structure.
- A selected arc defaults to no more than 30 Level 2 event cards and never exceeds 240 rendered
  items.
- All fixture choices, gates, effects, endings, and unresolved behavior stay on their correct
  deterministic paths. The small real-script smoke run preserves its five choices, nine effects,
  and unresolved records.
- Deterministic graph, requirement, effect, and evidence hashes are identical before and after AI
  organization.
- Every accepted event and claim links to existing beat/evidence IDs; unsupported causal language
  is labeled **Interpretation** or rejected.
- A user reaches arc -> choice -> requirement/effect -> exact evidence in at most three primary
  interactions.
- Cancellation returns control within two seconds and does not change the accepted map.
- An unchanged rerun uses cached chunks and makes no model calls.
- Reopening restores accepted organization, corrections, filters, selection, and navigation.
- Provider evidence records GPT-5.6 Luna, High reasoning, and disabled fast mode for every live AI
  acceptance call; a different or unavailable model never falls back silently.
- The UI remains responsive during analysis and organization.
- Independent review has no unresolved P0-P2 finding and no accepted P3 correctness/security
  finding.
- Pytest, Ruff, strict mypy, `pip check`, Windows UI checks, and milestone end-to-end checks pass.

After acceptance, update this plan with actual provider/model evidence, commits, worker tasks,
metrics, limitations, and deferred storage optimization; write the M05 completion report; include
screenshots of the welcome, arc overview, event branch, AI review, and exact-evidence states; create
the native M05 infographic; open one M05 PR and leave it unmerged; then complete the single M05
self-goal and stop.

Explicit exclusions and assumptions:

- No conversational Q&A, ask-the-story workflow, automatic ending finder, installer, packaging,
  public release, macOS support, game editing, or patching.
- AI cannot create, delete, or redirect authoritative graph edges, requirements, effects, or
  evidence.
- Rich-evidence cloud permission exists only after the in-app per-run confirmation.
- M05 exposes only the consent-gated GPT-5.6 Luna cloud path, with High reasoning and fast mode
  disabled. No automatic provider or model fallback is permitted.
- Local LM Studio organization and full canonical-game AI-scale validation are explicitly deferred
  limitations and are not claimed as accepted M05 behavior.
- M05 completes the approved roadmap; no M06 is implied.

#### Completion evidence

- Schema-v4 organization storage, isolated Luna/High provider boundary, bounded reconciliation,
  deterministic quotient edges, review/apply/corrections, layered Story Explorer, adaptive Windows
  UI, complex fixture, and independent adversarial review are integrated.
- Final Windows CPython 3.12 verification passed 348 tests, Ruff, strict mypy across 34 source
  files, `pip check`, JSON/whitespace validation, normal Windows UI checks, and both live AI
  end-to-end paths.
- The complex fixture's corrected cached run produced four arcs, 33 events, and 77 evidence-backed
  claims with 12 cache hits, zero provider calls, and unchanged deterministic authority SHA-256
  `337e5158a1d62d22b7ee76f68b2704b2077343f75e9a14e4781f61aad08ed618`.
- The separately consented real `.rpy` smoke produced one arc, four AI events, 14 claims, and six
  deterministic fallback events. Its cached rerun used four hits and zero provider calls in 54 ms.
- The real source remained unchanged: SHA-256
  `d3a4e0a305c6c8a8d84ff5bd99845a4035f0bde7ce953699af71d607806d7f71`, 9,994 bytes,
  `2026-03-27T22:21:22.0000000Z`. Its deterministic authority remained
  `55b48b9e3202e50186aab7f96b3c22f7cd10c262a26b769413e3cf50a7910374`.
- Normal Windows rendering, AI review, accepted/technical comparison, exact evidence, cache reuse,
  source immutability, and the 240-item cap passed. The completion report, metrics, screenshots,
  and native infographic are retained under `docs/milestones/M05/`.
- Deferred limitations are LM Studio product validation, full canonical cloud organization,
  database compaction, packaging, and distribution. No M06 is implied.

### M06 - Safe Source Recovery and Correct Route Semantics

Status: Complete and merged through PR #9 at `0021650` on 2026-07-12.

Objective: accept common modern Ren'Py source forms without modifying or executing the game, and
prove whether alternatives are temporary detours, persistent routes, loops, or terminals before
presentation or AI organization.

Deliverables:

- One unified ingestion path for a game folder, parent folder containing `game`, direct `.rpy`,
  direct `.rpyc`, direct `.rpa`, and existing `.rsmproj` inputs.
- Deterministic precedence: loose original `.rpy`, archived original `.rpy`, loose reconstructed
  `.rpyc`, then archived reconstructed `.rpyc`; identical same-tier inputs deduplicate and
  conflicting same-tier inputs fail as ambiguous.
- Retain the existing bounded original RPA reader; do not vendor or invoke UnRPA.
- Bundle a reviewed, pinned runtime-only Unrpyc snapshot behind an isolated Windows helper. Never
  inject into, execute, or write beside the game. Disable network, shell use, arbitrary output,
  translation, injector behavior, multiprocessing, and permissive recovery modes. Bound time,
  memory, process count, input/output, logs, and decompression.
- Treat every recovered file and line as reconstructed evidence. Persist tool commit/bundle hash,
  input/output hashes, options, locator, and line basis. Never claim recovered lines are original
  author source lines.
- Provide an explicit recovered-source export to a user-selected destination outside the game,
  accompanied by provenance and warnings. Internal cache data remains outside the project and game.
- Modern Unrpyc-compatible inputs are the initial target. Ancient Python 2-era, obfuscated, or
  modified formats fail explicitly instead of falling back to unsafe behavior.
- Add schema-v5 source derivations, recovery results, incomplete-coverage state, procedure/loop
  summaries, control regions/arms, control ownership, edge roles, and explicit terminals.
- Normalize calls and call-site-specific returns, condense loop SCCs, compute post-dominators, and
  classify `local_detour`, `optional_detour`, `reconvergent_route_segment`, `persistent_route`,
  `terminal_split`, `loop_choice`, or `unresolved`.
- A concrete common post-dominator proves reconvergence. Relationship/point changes alone do not
  prove a lasting route. Persistent routes require non-reconvergent content, mutually exclusive
  downstream state dispatch, or distinct terminals. The virtual super-exit is never displayed.
- Preserve all ordered transition evidence and explicit semantic roles; remove dominant-edge
  quotienting as an authority for route shape.

Public boundaries:

```text
inspect_input(path, options, cancel_check) -> IngestionPlan
ingest_input(path, options, cancel_check) -> IngestionResult
analyze_control_flow(graph, semantic_story, gates, effects) -> ControlFlowAnalysis
```

The default compiled policy is automatic and strict. Partial recovery is opt-in, produces a
persistent incomplete-coverage warning, and blocks AI transmission until explicitly acknowledged.

Worker sequence:

1. Source-ingestion/recovery worker: unified discovery, precedence, isolated recovery, provenance,
   export, schema storage, and focused tests; no control analysis or UI redesign.
2. Route-semantics worker: procedure summaries, loops, post-dominators, control regions, edge
   roles, persistence, and focused fixtures; no recovery or M07 UI/AI work.
3. Tests/security/review worker: malicious and compatibility fixtures, migration and performance
   harnesses, independent diff review, and new tests only; production fixes return to owners.

All normal workers use GPT-5.6 Sol with High reasoning and fast mode disabled. GPT-5.6 Luna is not
used in M06 because M06 performs no story AI analysis.

Acceptance criteria:

- Windows CPython 3.12 full pytest, Ruff, strict mypy, `pip check`, `git diff --check`, and M06
  end-to-end checks pass.
- Recovery-helper packaging/isolation, timeout, cancellation, oversized output, corruption,
  ambiguity, cache replay, and provenance/export cases pass without game writes or execution.
- Synthetic simple/nested diamonds, optional scenes, long reconvergent segments, state dispatch,
  distinct/shared endings, loops, recursion, non-returning calls, and dynamic targets classify
  exactly as expected with stable IDs and byte-equivalent canonical output.
- MsDenvers curated walkthrough cases classify Days 1-19 variations as detours where they rejoin,
  Day 20 character paths as persistent routes, and reconvergent choices within a persistent route
  as local regions. The walkthrough is evaluation evidence only, never runtime input or authority.
- Every authoritative transition retains evidence and an explicit role or unresolved diagnostic;
  downstream mainline content is never duplicated once per reconvergent arm.
- Approximately 10,000 nodes and 15,000 edges analyze within two seconds on the trial Windows
  machine with under 256 MB additional peak memory and no per-event whole-graph BFS.
- If any canonical sample is accessed, its SHA-256, size, and `LastWriteTimeUtc` are identical
  before and after.

Explicit exclusions:

- No two-level UI redesign, parallel AI orchestration, LM Studio work, packaging/installer,
  executable/APK/ZIP scanning, legacy Python 2 recovery, game editing, or automatic cloud calls.

Completion evidence:

- Unified folder/direct `.rpy`/`.rpyc`/`.rpa`/project ingestion, schema-v5 provenance, safe export,
  the isolated Windows recovery helper, deterministic control regions, and persisted control-flow
  payloads are integrated on `codex/m06-safe-ingestion-route-semantics`.
- The pinned minimal Unrpyc runtime records upstream tag `v2.0.4`, internal version `2.0.3`, commit
  `3ae8334ed71a05535927dcc559663d3aca51215b`, and bundle SHA-256
  `fb764521f9d3120b0c62198f086226f837802d73eccc9cad3c2ad683b1117775`.
- Final Windows CPython 3.12 verification passed 376 tests, Ruff, strict mypy across 42 source
  files, `pip check`, whitespace validation, wheel-content inspection, and all independent-review
  regressions. Independent review found no remaining P0-P3 correctness or security issue.
- The 10,000-node/14,998-edge control harness completed in 1.419 seconds with about 26.5 MB peak
  traced memory. The adversarial 2,000-node persistent-split chain completed in 0.496 seconds with
  about 5.1 MB and bounded membership, replacing the rejected quadratic implementation.
- The read-only small `.rpy` produced 49 nodes/51 edges and one proven local detour. The read-only
  small `.rpyc` recovered successfully into 339 nodes/345 edges and two terminal splits; unchanged
  refresh parsed zero sources, reused one cached recovery, and preserved authority SHA-256
  `9dc1a23c5661937b5ecdaf6271cf0c3898acf0ec15744b2e45da3258d4695948`.
- Both small input files retained identical SHA-256, size, and `LastWriteTimeUtc`. The canonical
  `scripts.rpa` was not accessed during M06.
- Full AppContainer/restricted-token packaging remains a documented non-blocking limitation of the
  source-form milestone. The suspended Job Object, minimal environment, bounded helper, audit
  policy, cache isolation, and no-game-write rules are implemented and tested.

### M06.5 - Local Browser Interface Bridge

Status: Complete and merged through PR #10 at `e24509c` on 2026-07-12.

Objective: make a locally served browser interface the primary Windows UI without changing the
local/offline product boundary or implementing the M07 two-level route redesign and parallel AI
work early.

Deliverables:

- A Python launcher that binds only to `127.0.0.1` on an ephemeral port, creates an unguessable
  session token, opens Chrome/default browser, and shuts down cleanly.
- A typed local JSON API over the existing project, presentation, ingestion, organization, and
  evidence services. The browser never receives arbitrary filesystem authority.
- Native Windows source/project selection initiated from the browser through a narrowly scoped
  local dialog boundary; game contents are not uploaded or copied through a remote service.
- Browser equivalents for welcome/recent projects, create/open/refresh, progress/cancel, current
  Story Explorer/map, selection, inspector/evidence, search, filters, zoom/fit, organization
  consent/review/apply/discard, diagnostics, and durable settings where those capabilities already
  exist.
- A polished local-first visual system with keyboard focus, accessible names, responsive layout,
  100%/200% zoom support, bounded rendering, and no unnecessary helper copy.
- Strict loopback, Host/Origin/session/CSRF, CSP, cache, upload/body-size, path, and error-redaction
  controls. Static assets are packaged locally; there are no remote scripts, fonts, analytics, or
  implicit cloud calls.
- Keep the old PySide6 interface as an explicitly labeled legacy fallback for this bridge; do not
  maintain two independent analysis implementations.
- Automated API, security, browser interaction, project lifecycle, cancellation, and regression
  tests plus an independent review.

Acceptance criteria:

- Windows CPython 3.12 full pytest, Ruff, strict mypy, `pip check`, and `git diff --check` pass.
- Chrome end-to-end checks pass at 100% and 200% zoom for welcome, project opening, bounded map,
  search/filter, selection, direct evidence traversal, project reopen, progress/cancel, and an
  organization review path using mocked/local deterministic data without an implicit provider run.
- The server cannot bind non-loopback, rejects invalid Host/Origin/session/CSRF and oversized
  bodies, emits a restrictive CSP, does not expose local paths in routine UI/error responses, and
  leaves no background process after exit.
- Existing deterministic graph, M06 route analysis, provenance, project hashes, AI consent, cache,
  and correction semantics remain authoritative and are not duplicated in JavaScript.
- Opening or rendering a project invokes no provider. No game code runs, no game/source file is
  modified, and no story text is sent to any remote origin.
- Browser rendering remains bounded by the existing presentation limits and a selected item can
  reach exact source evidence.
- Independent review has no unresolved P0-P2 or accepted P3 correctness/security finding.
- Required M06.5 goal, task ledger, completion report, native infographic, and one unmerged PR are
  complete. M07 remains unstarted.

Explicit exclusions:

- No hosted/cloud web deployment, remote access, multi-user service, account system, telemetry,
  installer, or public release.
- No M07 two-level route-map redesign, parallel Luna orchestration, full-game AI rerun, LM Studio,
  or new AI behavior.
- No duplication or rewrite of the deterministic analyzer in TypeScript/JavaScript.

### M07 - Two-Level Route Map and Resumable Parallel AI

Status: Complete and merged through PR #11 at `4c421a1` on 2026-07-12.

Objective: replace the three-level card hierarchy with the two-level Route Map and Detail/Evidence
experience in Section 4, then make optional story enrichment scope-based, resumable, measurable,
and substantially faster.

Planned deliverables and locked decisions:

- A chronological story-spine Route Map with compact milestones, visible fork/merge lines, edge
  gates, detour lanes, persistent route lanes, loops, and distinct terminals. Default initial view
  targets no more than about 30 meaningful nodes; technical fallback becomes corridor/coverage
  metadata rather than singleton cards.
- One Detail and Evidence workspace reached directly from any map element; no third level.
- Deterministic route scopes are complete before AI runs. AI may name, summarize, and interpret
  existing evidence but cannot decide edges, routes, gates, effects, merges, or endings.
- Actual story analysis uses GPT-5.6 Luna with High reasoning and fast mode disabled. Normal Codex
  implementation/review work uses GPT-5.6 Sol High with fast mode disabled.
- Cloud analysis starts with eight independent workers and may ramp to twelve, with immediate
  throttling on rate limits, latency, or errors; at most two repairs run concurrently. Persistence,
  accounting, conflict resolution, and final deterministic assembly remain serialized.
- Scope checkpoints persist `pending`, `cached/in-flight`, `validated`, `fallback`, `failed`, or
  `cancelled`. Validated scopes survive cancellation and resume. Global all-or-nothing arc fallback
  is removed from the default path.
- Persist token/call usage after each provider attempt, normalize cache identity across identical
  global/scoped inputs, use adaptive timeouts and budgets, show honest coverage and ETA ranges, and
  present validated partial results when a soft time/token target is reached.
- Ten minutes is an optimization target, not an SLA. A full MsDenvers cloud rerun requires a
  separately confirmed scope and budget and is not triggered automatically.
- The official walkthrough remains a diagnostic oracle only and is never a product dependency.

M07 acceptance will include deterministic completion-order tests, cancellation/resume, zero-call
cache replay, throttling and budget controls, native Windows UI testing at 100% and 200%, font and
accessibility checks, direct evidence traversal, bounded node density, and explicit AI-versus-
technical coverage.

### M07.1 - Safety and Real-Project Closure

Status: Complete and merged through PR #12 at `32e9a3c` on 2026-07-13.

Objective: close the correctness and real-browser gaps found after M07 without broadening the
product, deleting the legacy fallback, or weakening deterministic authority.

Locked deliverables:

- Enforce recovered-source cloud-transmission blocking both when preparing organization and
  immediately before every provider call. A browser acknowledgement must be explicit, narrowly
  scoped, persisted, and revalidated.
- Bind conservative aggregate call, token, and elapsed-time budgets plus single-use consent to the
  exact prepared generation and scope set. Provider work must not begin when that binding is stale,
  incomplete, or absent.
- Deterministically partition every normal and repair request below the provider's 48,000-character
  request boundary using the actual serialized prompt, including the M07 route fixture. Preserve
  validated work across cancellation and resume, and persist accounting after each attempt.
- Make accepted AI assemblies generation-safe. Refresh must invalidate or reject stale drafts and
  overlays, and the product must retain and display evidence-backed claims, corrections, and pins.
- Align the browser with the real evidence/detail API schema so exact qualified source lines and
  provenance display correctly.
- Replace hard-coded route rows with arbitrary deterministic lane geometry. Preserve fork, merge,
  loop, terminal, gate, and cross-page continuation truth without inventing or silently dropping
  edges.
- Report asynchronous refresh success only after the backend operation finishes.
- Add a live Chrome acceptance path through the loopback server and real `ProjectApi` against a
  temporary SQLite project. Opening and navigating must make no provider or remote call. Production
  assets must not depend on a mock-project mode.
- Complete independent defect review, Windows acceptance, milestone documentation, and a native
  infographic on one unmerged pull request.

Explicit exclusions:

- No live full-game Luna rerun, LM Studio work, installer, hosted service, analyzer rewrite, legacy
  desktop deletion, storage consolidation, source-recovery expansion, or canonical archive access.
- No visual simplification that hides deterministic gates, effects, unresolved behavior, or source
  evidence.

### M08 - Web-Only AI Story Understanding Validation

Status: Complete and merged through PR #13 at `0ed8d72` on 2026-07-13. Follow-up launcher and
Route Map allocation fixes were merged through PRs #14 and #15.

Completion result: the packaged product is now browser-only. Evidence-grounded GPT-5.6 Luna
organization is the default human-readable story layer after acceptance, with Technical Structure
retained as the deterministic authority and fallback. Exact bounded consent, ownership-scoped
claims, partial fallback, resumable checkpoints, honest current-run accounting, topology-complete
pagination, two-level Detail / Evidence navigation, and zero-provider open/replay behavior are
verified. Corrected live results accepted 51/53 complex-fixture scopes, 8/8 small `.rpy` scopes,
0/5 compiled-only scopes with intentional technical fallback, and 1/4 bounded MsDenvers windows;
all four retained 100% deterministic technical coverage and unchanged authority hashes. See
`docs/milestones/M08/COMPLETION_REPORT.md` for commands, metrics, limitations, and review evidence.

Objective: remove the obsolete standalone Windows graph application and prove, on controlled real
story inputs, that evidence-grounded GPT-5.6 Luna organization produces a substantially more useful
human story map than deterministic structure alone.

Product contract:

- The loopback browser interface is the sole supported product surface. Remove the legacy
  `renpy-story-mapper-gui` entry point, QGraphicsView workspace, desktop-only assets/tests, and
  instructions. A minimal local Windows picker may remain only as an implementation detail of the
  browser workflow.
- Deterministic analysis remains the authority for source selection, connections, choices,
  conditions, requirements, effects, reconvergence, persistent routes, loops, calls, returns,
  endings, unresolved behavior, and source evidence.
- AI is the required stage for the finished human-readable map: scene boundaries, meaningful
  events, titles, summaries, character development, route meaning, importance, and broad story
  arcs. The technical map remains visible for verification, failure recovery, and privacy-first
  operation, but is not presented as the finished reading experience.
- Cloud analysis uses GPT-5.6 Luna with High reasoning and fast mode disabled. Opening or rendering
  a project never invokes AI. Rich story transmission requires exact explicit consent, including
  recovered-source acknowledgement where applicable. LM Studio remains deferred.

Locked deliverables:

1. Remove the legacy standalone desktop product surface without duplicating backend behavior in
   JavaScript or weakening the local-only browser security boundary.
2. Establish a checked-in evaluation manifest and expected-result schema covering the generated
   complex branching fixture, small real `.rpy`, small recovered `.rpyc`, and bounded MsDenvers
   walkthrough-backed scopes. External copyrighted story text and walkthrough contents remain
   outside the repository; fixtures store only permitted synthetic content, fingerprints, scope
   identifiers, and expected structural/narrative assertions.
3. Preserve the deterministic-before-AI baseline and expose a clear Technical Structure versus AI
   Story Map comparison. The broad AI view is a stable quotient graph: validated AI events become
   the visible boxes, while deterministic code projects only the real cross-event connections and
   retains their underlying gates, effects, route roles, and evidence. It must not merely rename
   every technical node. Accepted AI organization remains selectable for comparison; the later
   deterministic M10 inspection remains the normal default. Detail / Evidence is the only second
   user-visible level.
4. Use the existing resumable parallel scope scheduler for Luna analysis, with evidence-complete
   scene/event output, cross-scope reconciliation, cache reuse, partial validated results, and no
   all-or-nothing global collapse.
5. Display AI coverage, technical fallback, pending/failed scopes, calls, tokens, elapsed time, ETA,
   consent/provider identity, and cache reuse. Preserve cancel/resume and review/apply/discard.
6. Produce a reproducible evaluation report comparing deterministic structure, AI organization,
   and curated expected story meaning: scene boundaries, meaningful events, route names, character
   developments, temporary detours, persistent routes, loops, and endings.
7. Run live AI only on separately consented bounded inputs. Start with the synthetic and small
   scripts; use selected MsDenvers scopes and its official walkthrough only as diagnostic evidence,
   never as a runtime dependency. Do not repeat the prior unrestricted full-game run in M08.

Acceptance criteria:

- No legacy standalone GUI entry point or QGraphicsView product code ships in the wheel; the local
  browser can create/open/refresh a project and reach both Technical Structure and AI Story Map.
- Every AI event, arc, claim, promoted character, and outcome references existing evidence IDs;
  AI cannot invent or redirect factual graph structure, gates, effects, routes, or endings.
- The complex fixture and both small real-source forms complete the evaluation workflow with stable
  deterministic authority before/after AI, clear coverage/fallback metrics, persisted accepted
  results, and zero-call unchanged replay.
- Selected MsDenvers scopes are compared with curated walkthrough expectations for reconvergent
  variations, persistent character routes, important events, and endings. Disagreements are
  recorded honestly and corrected through prompt/assembly changes or documented limitations.
- The AI Story Map is demonstrably more readable than Technical Structure according to the checked
  evaluation rubric; if it is not, M08 remains incomplete.
- Cancellation preserves validated scopes, resume avoids repeating them, and partial validated
  results remain reviewable when a soft budget is reached.
- Opening/reopening/navigation causes zero provider or remote calls. Every live story transmission
  is consented and records Luna/High/no-fast-mode identity, calls, tokens, time, and hashes.
- Windows CPython 3.12 full pytest, Ruff, strict mypy, `pip check`, `git diff --check`, wheel
  inspection, real Chrome tests at 100% and 200%, milestone end-to-end evaluation, and independent
  review complete with no unresolved P0-P2 finding.
- `GOAL.md`, `TASKS.md`, `COMPLETION_REPORT.md`, and native `INFOGRAPHIC.png` exist. One M08 PR is
  opened and left unmerged.

Explicit exclusions:

- No LM Studio validation, hosted service, installer, standalone executable, macOS work, game
  editing/patching, full unrestricted MsDenvers rerun, automatic cloud calls, or deterministic
  analyzer rewrite.
- The official walkthrough is evaluation evidence only and is never required for analyzing an
  arbitrary game.

### M09 - Static Story Metadata Enrichment

Status: Complete on `codex/m09-static-story-metadata` as of 2026-07-13; PR #16 is intentionally
left unmerged for user review.

Completion result: selecting a game folder with exact `scripts.rpa` now keeps that archive as the
sole chronology/connectivity authority while exact `extras.rpa` is recovered into a quarantined
metadata-only lane. Literal character aliases, scalar defaults, supported variable meanings, and
optional exact-key titles are persisted with provenance and projected onto the shipped browser
Route Map/Detail responses without changing graph or route authority. Loose replay modules and
media archives do not enter canonical story analysis. The final read-only MsDenvers run found 84
usable aliases, 109 declared defaults, 15 readable state labels, and 13 optional titles across 52
canonical and 5 secondary sources; its authority hash remained unchanged, its archives remained
byte/timestamp identical, and no AI or game Python ran. See
`docs/milestones/M09/COMPLETION_REPORT.md` for exact commands, metrics, review corrections, and
limitations.

Objective: improve the human readability of recovered games by statically extracting a narrow set
of names and categories from companion Ren'Py modules, without executing creator code or changing
the authoritative story graph.

Locked deliverables:

- Keep `scripts.rpa` and the selected story modules authoritative for chronology and connectivity.
- Discover only relevant companion `.rpy`/`.rpyc` modules and statically extract supported literal
  character aliases, default state declarations, variable display meanings/categories, and
  optional human scene titles.
- Persist source provenance and apply metadata to existing speaker, state-variable, and
  presentation labels. User edits continue to take precedence over extracted hints.
- Mark gallery/replay sources as secondary and never merge their labels into canonical routes.
- Exclude images, audio, fonts, shaders, cache bytecode, and unrelated UI code.
- Verify the behavior with synthetic fixtures and a read-only MsDenvers folder check; no cloud AI
  call is required or permitted by this milestone.

Acceptance criteria:

- No game or Ren'Py Python executes, no source/game file is modified, and dynamic or ambiguous
  metadata constructs are skipped with bounded diagnostics.
- Every accepted metadata item retains locator, fingerprint, line basis, and exact source span.
- Graph, route, gate, effect, and evidence authority remain byte-equivalent before and after
  enrichment; replay/gallery labels do not become canonical story routes.
- Metadata persists across reopen and refresh, and changed companion inputs invalidate only their
  metadata.
- The browser displays improved readable speaker/state/scene labels without provider or remote
  calls.
- Windows CPython 3.12 pytest, Ruff, strict mypy, `pip check`, milestone end-to-end/browser checks,
  and independent review pass with no unresolved P0-P2 issue.
- Required M09 artifacts and one unmerged M09 pull request are complete.

Explicit exclusions:

- No AI-provider work, live story analysis, LM Studio, media ingestion, thumbnails, generalized
  Python evaluation, hosted deployment, installer, game editing, or replay chronology.

### M10 - Canonical deterministic inspection graph

Status: Complete and merged through corrective hardening.

M10 owns the generation-bound canonical graph, bounded simplified structural inspection,
deterministic reachability and branch provenance, whole-authority search/focus, and safe local
browser inspection. It does not infer human chapters, solve arbitrary paths, or make AI narrative
claims.

### M11 - Human story scenes and chapters

Status: Complete and merged through PR #20 at
`26502e88bd81b7a1934a6957724fd62f7ba5fbec` on 2026-07-15.

M11 owns human story scenes and scene/chapter presentation derived from deterministic evidence.
It may improve narrative readability without replacing the M10 canonical authority.

### M12 - Route-to-target solving

Status: Complete and merged through [PR #22](https://github.com/nmpraveen/renpy-story-mapper/pull/22)
with normal merge commit `f67df8a7cb805bf4adf8590585bae700d2f3117f` on 2026-07-16.

M12 owns route-to-target solving and explicit path requirements. It must remain conservative for
unresolved or dynamic behavior and must not claim arbitrary expression satisfiability.

### M13 - AI narrative layer

Status: Verification on existing unmerged PR #23. The recorded semantic `PASS` remains valid.
Historical runtime `3533d49a61e77c76794b4ba8338ccf60ee8201ef`, targeted-review head
`e79384b`, approved live/replay head `677d881`, and unbounded GitHub run `29604661539` at
`7bf5404` retain their exact-head evidence only. The final bounded correction integrated at
`9ab1dbd`, and focused verification passed at `532eefc`. Additional correction `a7e242b` passes its
intended reopen regression, 54 focused tests, Ruff, strict mypy, and diff checks, but independent
rereview found one P1: duplicate durable reservations for the same reused logical attempt collapse
to one recovered history slot. PR #23 is not currently ready and the reviewed local correction
head has not been pushed.

M13 owns the optional AI narrative layer: titles, summaries, characters, motives, and
chapter/route/full-plot summaries. AI output remains evidence-linked, reviewable, and subordinate
to deterministic authority.

### M14 - Dynamic adapters and optional tracing

M14 owns dynamic framework adapters and optional runtime tracing. It is deferred indefinitely for
now and is not part of M10-M13 implementation work.

## 8. Product completion definition

After M05, the planned product is complete when the user can:

1. Select a complex Ren'Py game folder or archive on Windows.
2. Wait for safe static analysis without the game being executed or modified.
3. See a clean Route Map rather than hundreds of technical nodes.
4. Follow choices, requirements, effects, detours, persistent routes, merges, loops, and endings.
5. Open Detail and Evidence to inspect exact dialogue, code expressions, and qualified source lines.
6. Understand important relationship, love/lust, skill, money, job, flag, and progression changes.
7. Correct AI grouping or names when necessary.
8. Close and reopen the project without repeating unchanged work.

Packaging or sharing the application may be reconsidered later, but it is not required for product
completion.

## 9. Permanent orchestration model

The existing permanent orchestrator owns this plan, the active milestone goal, worker-task links,
integration, Windows verification, completion reports, and milestone infographics.

### Milestone gate

- Work on exactly one milestone at a time.
- Create exactly one self-goal only after the user explicitly approves that milestone.
- Use user-visible local Codex tasks for major independent implementation, fixtures/tests, review,
  or substantial documentation.
- Give each worker a bounded brief, base commit, branch/worktree, owned files, deliverables, tests,
  exclusions, and return contract.
- Record every worker in `docs/milestones/<milestone-id>/TASKS.md`.
- Inspect actual diffs and evidence; a worker saying "done" is not proof.
- Integrate on one milestone branch and use one PR per milestone.
- Never merge a PR without explicit user approval.
- Do not begin the next milestone until the current milestone has passed Windows acceptance,
  documentation, native infographic generation, and user review.

### Required milestone artifacts

```text
docs/milestones/<milestone-id>/
  GOAL.md
  TASKS.md
  COMPLETION_REPORT.md
  INFOGRAPHIC.png
```

The completion report is the factual authority and must record scope, delivered behavior, worker
tasks, commits, exact verification commands/results, canonical-sample evidence, archive
immutability, limitations, and deferred work.

Generate `INFOGRAPHIC.png` with Codex's native image-generation capability. Do not substitute SVG,
Mermaid rendering, Python drawing, manually composed shapes, or an external image API. Generated
image text may be imperfect, so the Markdown report remains authoritative.

### Windows acceptance suite

Every milestone must run, as applicable:

- pytest
- Ruff
- strict mypy
- `pip check`
- milestone-specific end-to-end checks
- Windows UI checks for M04 and M05
- canonical archive fingerprint before and after any access

Record commands, exit codes, test counts, deterministic output hashes where relevant, elapsed time,
and unresolved items.

## 10. Repository and safety rules

- Repository: `nmpraveen/renpy-story-mapper`
- Windows runtime: CPython 3.12
- Canonical read-only sample: the locally held private `scripts.rpa`; its machine-specific path is
  deliberately excluded from repository documentation.
- Never modify, replace, rename, unpack into, or write beside the canonical archive.
- Put outputs in the repository worktree or a Windows temporary directory.
- Before and after archive access, record SHA-256, size, and `LastWriteTimeUtc`.
- Never commit the sample archive, extracted game content, credentials, virtual environments,
  caches, or temporary outputs.
- Preserve unrelated user changes.
- Do not weaken deterministic evidence or safety boundaries to make a cleaner picture.
- Do not implement future-milestone features inside the active milestone.

## 11. Current next action

Hold M13 in Verification at independently reviewed correction head `a7e242b`. The explicitly
authorized additional correction/rereview has been consumed and rereview still reports one P1 in
duplicate recovered-reservation multiplicity. Do not push the known-defective correction head, run
provider/live acceptance, merge PR #23, or begin M14. Resume only with explicit authorization for
another narrowly bounded correction and rereview.
