# Ren'Py Story Mapper - Windows Master Plan

Last revised: 2026-07-10

Status: M01, M02, M03, and M04 are complete. M05 is planned but has not been approved or started.

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

Status: Complete on `milestone/m04-three-level-windows-map`; implementation and Windows
acceptance finished on 2026-07-10. The milestone PR is intentionally left unmerged for user
approval as PR #6.

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

### M05 - AI-organized story map and final product validation

Status: Next proposed milestone; do not create its goal or begin work without explicit approval.

Objective: turn the accurate but technical map into the readable story flowchart originally
requested, while keeping every connection, requirement, and effect anchored to deterministic
evidence.

Deliverables:

- Minimal provider-neutral AI boundary and one working provider adapter selected at milestone
  start; additional providers are optional future work.
- Explicit opt-in before sending story text to any cloud provider.
- Structured AI output for event boundaries, event titles, concise summaries, involved characters,
  major state changes, arc grouping, and Level 1 outcome descriptions.
- Chunking strategy for long labels and branches, followed by evidence-aware reconciliation across
  chunks.
- Graph-constrained grouping: AI may group or describe existing beats and paths but cannot create,
  delete, or redirect authoritative edges.
- Requirement/effect-aware summaries so important gates and point changes are not lost during
  compression.
- Separate display for proven facts, AI interpretation, and unresolved behavior.
- Hash/model/prompt-version cache, cancellation, retry, and safe provider-failure handling.
- User review tools to rename, split, merge, recategorize, approve, or reject AI-created events and
  arcs. User corrections override AI output and survive refreshes.
- Final visual and usability refinement of all three map levels.

Acceptance criteria:

- On the canonical sample, `new_prologue` is divided into a manageable set of coherent,
  human-readable events instead of remaining one 196-beat scene.
- Level 1 shows a concise story overview; Level 2 shows meaningful events, choices, gates, and
  effects; Level 3 preserves the exact deterministic evidence.
- Important conditions such as Wits or Charisma requirements remain visibly attached to the
  correct choices after AI grouping.
- Relevant changes such as love/lust/relationship points, flags, jobs, and chapter progression are
  surfaced at the appropriate level and never silently discarded.
- AI summaries do not alter the M01/M02/M03 authoritative edge, gate, or effect sets.
- Every AI-created event and high-level claim links to its supporting beats and source evidence.
- Unsupported causal claims are marked as interpretation or omitted, never stated as proven.
- Provider failure, cancellation, or disabled AI falls back to the deterministic layered map
  without damaging the project.
- Reprocessing unchanged content uses cached results.
- The user can correct bad grouping or naming without editing the game.
- A final Windows walkthrough demonstrates importing the canonical archive, navigating all three
  levels, following at least one branched choice with a requirement and effect, and returning to
  its exact source evidence.
- Pytest, Ruff, strict mypy, `pip check`, Windows UI checks, and milestone-specific end-to-end tests
  pass.

Explicit exclusions:

- No conversational Q&A or "ask the story" feature.
- No separate advanced-exploration milestone.
- No installer, packaging, distribution, release publishing, or portable-report milestone.

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

Present the completed M04 report, infographic, and unmerged milestone PR for user review. Wait for
explicit approval before creating the M05 goal or beginning any M05 implementation.
