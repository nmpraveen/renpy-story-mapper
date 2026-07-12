# Ren'Py Story Mapper - Windows Master Plan

Last revised: 2026-07-11

Status: M01, M02, M03, and M04 are complete. M05 is approved and active on
`milestone/m05-ai-story-explorer` from synchronized `main` commit `0ae86f7`.

## 1. Product goal

Build a private Windows application that accepts a Ren'Py game folder or `scripts.rpa` archive and
turns the story into a readable, interactive flowchart.

The application is for understanding complicated branching stories. It is not a chatbot, a game
editor, or a public distribution project. The main experience is:

```text
Select a Ren'Py game
  -> analyze it without running game code
  -> identify story paths, choices, requirements, and state changes
  -> organize the result into human-sized story events
  -> explore the story at three levels of detail
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

## 4. The three-level story map

The application must provide semantic zoom: zooming out simplifies the story, and zooming in
reveals progressively more evidence. It must not merely make the same hundreds of boxes physically
smaller or larger.

### Level 1 - Story overview

Purpose: understand the big picture at a glance.

Show a small number of major arcs, turning points, relationships, roles, and outcomes. Examples:

```text
Person A meets Person B
  -> relationship grows
  -> Person A joins Company Z
```

Level 1 should emphasize:

- chapters or major arcs
- important relationship changes
- major career, location, allegiance, or route changes
- major branch points and endings
- concise outcome summaries

It should hide routine dialogue, image/audio commands, pauses, save setup, and most implementation
details.

### Level 2 - Story events and choices

Purpose: understand how the story progresses and branches.

Show human-sized events rather than one node per line or one node per label. Each event may show:

- a readable event title and short summary
- involved characters
- player choices
- incoming requirements or gates
- outgoing effects and important state changes
- branch merges, loops, shared calls, and endings
- warnings when a connection or effect is unresolved

Examples of visible annotations:

```text
[Requires: Ian Wits > 0]
[Choice: Offer help]
[Effect: Lust increases]
[Effect: Ian/Lena relationship points +1]
[Sets: Ian and Lena are dating]
```

### Level 3 - Exact evidence

Purpose: verify every conclusion and inspect small details.

Show the deterministic source-linked representation:

- exact dialogue and narration
- exact choice captions
- original conditions
- explicit assignments, increments, decrements, and relevant calls
- labels, jumps, calls, returns, fallthrough, and merge points
- file path and physical source lines
- technical commands on demand
- unresolved behavior with the reason it could not be resolved

Level 3 is where accuracy is audited. Levels 1 and 2 are readable projections over this evidence.

### Required interaction

- Mouse-wheel zoom and pan.
- Semantic transitions between Levels 1, 2, and 3.
- Expand or collapse a single arc, event, choice, or branch without expanding everything.
- Fit the current story, branch, or selection to the window.
- Preserve the user's location and selection while changing detail levels.
- Search by character, label, dialogue, choice text, variable, condition, or event title.
- Toggle technical nodes and unresolved items.
- Click any high-level claim to reveal the lower-level evidence supporting it.

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
Game folder or scripts.rpa
        |
Read-only inventory and .rpy precedence
        |
Safe static parser
        |
Authoritative source-linked control-flow graph (M01)
        |
Deterministic scenes, beats, and transitions (M02)
        |
Requirements, state effects, and durable project storage (M03)
        |
Three-level interactive Windows graph (M04)
        |
AI-assisted event grouping, titles, summaries, and high-level meaning (M05)
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
- PySide6 for the Windows desktop shell
- Native PySide6 `QGraphicsView` canvas, selected by M04 for offline Windows behavior, bounded
  rendering, native accessibility, and deterministic headless testing
- One minimal provider-neutral AI interface with only the provider adapter needed for the first
  working version; multiple provider integrations are not a milestone requirement

PyInstaller packaging, an installer, public distribution, macOS support, game editing, and game
patching are outside the active plan.

## 7. Remaining milestones

The approved roadmap contains M03 through M05. M03 and M04 are complete, leaving exactly one
planned milestone. Do not create M06 or M07. Ideas beyond M05 belong in a future backlog and are
not commitments.

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

Status: Approved and active from synchronized `main` commit `0ae86f7` on
`milestone/m05-ai-story-explorer`. M05 is the final milestone in the currently approved roadmap.

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

## 8. Product completion definition

After M05, the planned product is complete when the user can:

1. Select a complex Ren'Py game folder or archive on Windows.
2. Wait for safe static analysis without the game being executed or modified.
3. See a clean Level 1 overview rather than hundreds of technical nodes.
4. Zoom into Level 2 events and follow choices, requirements, effects, merges, and endings.
5. Zoom into Level 3 to inspect exact dialogue, code expressions, and source lines.
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
- Canonical read-only sample:
  `C:\Users\prave\University of Michigan Dropbox\Praveen Manivannan\Windows Mac portal\scripts.rpa`
- Never modify, replace, rename, unpack into, or write beside the canonical archive.
- Put outputs in the repository worktree or a Windows temporary directory.
- Before and after archive access, record SHA-256, size, and `LastWriteTimeUtc`.
- Never commit the sample archive, extracted game content, credentials, virtual environments,
  caches, or temporary outputs.
- Preserve unrelated user changes.
- Do not weaken deterministic evidence or safety boundaries to make a cleaner picture.
- Do not implement future-milestone features inside the active milestone.

## 11. Current next action

Execute only M05 under its single active self-goal. Integrate the story-model and provider
contracts first, then deterministic layout, then the Story Explorer UI, and finally independent
review and complete Windows/canonical acceptance. Produce one unmerged M05 PR and stop for explicit
user approval. Do not create M06.
