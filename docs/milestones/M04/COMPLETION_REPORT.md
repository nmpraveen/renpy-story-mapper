# M04 Completion Report - Three-Level Windows Story Map

Completion date: 2026-07-10

Milestone branch: `milestone/m04-three-level-windows-map`

Base commit: `0bb53ef88db3428a7e2625724496fad0f3506afd`

Runtime authority: Windows, CPython 3.12.10

Milestone PR: pending creation; it will remain unmerged for user approval

## Outcome

M04 delivers a local-first PySide6 Windows application that opens a folder, archive, or durable
`.rsmproj` project and presents the deterministic Ren'Py analysis as a bounded three-level story
map. The application does not execute embedded Ren'Py or game Python, does not require AI, and
does not write to the selected game source.

The canonical copied project reached an 80-node overview with 120 visible edges, expanded
`new_prologue` into 49 structural event groups, showed exact choice requirements and effects, and
descended to source-linked Level 3 evidence. The canvas rendered 200 items at overview, below its
hard 240-item cap, instead of attempting to materialize the entire game graph.

## Architecture and flow

1. The user selects a read-only game folder or RPA 3.0 archive in the PySide6 shell, or opens an
   existing `.rsmproj` file.
2. Existing deterministic static analysis supplies labels, beats, branches, conditions, jumps,
   calls, returns, fallthrough, state facts, and physical source evidence without running game
   code.
3. A schema-v3 SQLite presentation index materializes deterministic Level 1 containers, Level 2
   structural event groups, Level 3 beats/evidence, display facts, and search rows.
4. Bounded indexed queries feed a native `QGraphicsView` canvas. The default page is capped, and
   exact search focus can retrieve an off-page result without rendering the entire project.
5. Background workers keep project open, analysis, refresh, indexing, search, and evidence work
   outside the UI thread. Cancellation and sanitized errors preserve the saved project.
6. User renames, hidden-node choices, variable display names, and categories persist in the
   project without changing deterministic graph authority.

## Delivered capability

- Windows project lifecycle shell for folder/archive selection, project create/open/refresh/close,
  progress, cancellation, diagnostics, safe output-path validation, and saved-project recovery.
- Native semantic graph canvas with pan, wheel zoom, fit, selection, keyboard navigation, stable
  per-level center/selection restoration, and distinct deterministic node/edge styles.
- Level 1 bounded label/chapter containers, Level 2 deterministic structural event groups, and
  Level 3 exact beats and physical-line evidence.
- Search with bounded exact focus for results outside the current page.
- Choice outcome traversal, visible requirements/effects, variable/category filters, and
  technical/unresolved controls.
- Source evidence inspector and point-lookup indexes for evidence, facts, source nodes, and source
  edges.
- Durable node rename/hide and state-variable display/category overrides.
- Windows launcher and user-facing operating instructions in `README.md`.
- Canonical end-to-end Qt acceptance harness in `scripts/m04_ui_acceptance.py`.

## Worker tasks and integration

| Task ID | Responsibility | Branch and worktree | Delivered commits | Integration result |
| --- | --- | --- | --- | --- |
| `019f4ec5-acb6-7043-ae45-a9026297c24b` | Bounded deterministic presentation model | `codex/m04-presentation-model`; `C:\Users\prave\.codex\worktrees\7d68\Renpy` | `77d6089`, correction `db908fb` | Integrated as `8bf3087` and `956b09e`; later optimized and hardened on the milestone branch |
| `019f4ec5-acbe-74f2-8115-f6ae0381aea9` | Windows project lifecycle shell | `codex/m04-windows-shell`; `C:\Users\prave\.codex\worktrees\71fd\Renpy` | `24ac0a6` | Inspected and integrated as `97d0d7c` |
| `019f4ec5-acb8-7830-89cf-ec6ad4a38856` | Virtualized semantic graph canvas | `codex/m04-graph-canvas`; `C:\Users\prave\.codex\worktrees\0eb3\Renpy` | `d152a3a`, correction `be32fba` | Integrated as `1bb5ef6` and `e54f975` after encoding and stale-selection fixes |
| `019f4ef9-2881-71f2-aa00-2d7c43e6349f` | Independent contract and UI review | `codex/m04-independent-review`; `C:\Users\prave\.codex\worktrees\b7af\Renpy` | `19a3a41` | Adversarial test integrated as `409a88b`; final review found no remaining P0-P3 issues |

The orchestrator inspected each delivered diff before integration. The presentation model's first
delivery was returned for stale derived-index generation and incomplete Level 2/renamed-title
search. The canvas delivery was returned for encoding and stale selection. Independent review
then drove corrections for incomplete choice effects, non-point child lookups, lost cross-level
selection, missing variable display names, missing control-flow styling, full descendant evidence
and fact scans, and source-edge choice traversal. Each correction received regression coverage.

The final rendered canonical walkthrough exposed one additional gap: a result beyond the bounded
overview page could be found but not focused. Commit `6489985` added a bounded exact-focus request
and a 100-label regression. The canonical Qt harness subsequently reached the off-page
`new_prologue` result and completed the Level 1 -> Level 2 -> Level 3 workflow.

## Windows verification

All commands ran from the milestone branch on Windows with CPython 3.12.10. Exit code was `0` for
every command below.

| Check | Command | Result |
| --- | --- | --- |
| Full tests | `.\.venv\Scripts\python.exe -m pytest` | 133 passed in 4.43 seconds |
| Focused M04 contracts | `.\.venv\Scripts\python.exe -m pytest tests\test_m04_contract.py` | 11 passed in 1.00 seconds |
| Lint | `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed |
| Strict typing | `.\.venv\Scripts\python.exe -m mypy src\renpy_story_mapper` | Passed across 22 source files |
| Environment consistency | `.\.venv\Scripts\python.exe -m pip check` | No broken requirements |
| Canonical Qt workflow | `.\.venv\Scripts\python.exe scripts\m04_ui_acceptance.py artifacts\m04-acceptance\canonical.rsmproj` | Passed end to end |
| Patch hygiene | `git diff --check` | Passed |

Independent review separately passed 132 tests and 10 focused contracts on its reviewed head,
plus Ruff, strict mypy, and `pip check`. Its final report contained no P0-P3 finding.

## Canonical end-to-end evidence

The canonical source archive was accessed read-only at:

`C:\Users\prave\University of Michigan Dropbox\Praveen Manivannan\Windows Mac portal\scripts.rpa`

All generated databases and results were placed under the repository's ignored
`artifacts\m04-acceptance` directory. The archive was never extracted beside, renamed, replaced,
or modified.

### Performance and bounded presentation

| Measurement | Verified result |
| --- | ---: |
| First schema-v3 presentation build on copied project | 136.324 seconds |
| Second project open plus overview | 2.457 seconds |
| Canonical native Qt open to overview | 4.768 seconds |
| Overview query | 0.013 seconds |
| Variable search | 0.010 seconds |
| Overview evidence lookup | 0.004 seconds |
| Choice outcome facts lookup | 0.004 seconds |
| Off-page search and focus in Qt workflow | 8.008 seconds |
| SQLite project size | 2,260,058,112 bytes |
| Python `tracemalloc` peak during measured query workflow | 1,929,784 bytes |
| Overview result | 80 nodes, 120 edges, `has_more=true` |
| Rendered overview items | 200, below the 240-item hard cap |
| `new_prologue` Level 2 groups | 49 |
| Selected canonical choice | 4 requirements, 13 effects |
| Level 3 evidence slice | 3 nodes, 4 rendered items, 1 evidence record |

Presentation-index row counts were 318,980 nodes, 432,438 edges, 252,061 evidence rows, 94,333
facts, and 789,446 search rows. The measured deterministic result hash was
`b3812443125e29fa7318dc818d7b1acd92857468bc78cf46cef8724b3a04f969`.

A final repeat of the native Qt harness after the report and infographic were present passed with
the same structural counts and facts: 80 overview nodes, 200 rendered overview items, 49 event
groups, 4 choice requirements, 13 choice effects, 3 evidence nodes, 4 rendered evidence items,
and 1 evidence record. That cold-cache repeat opened in 22.985 seconds and focused the off-page
result in 7.331 seconds; the earlier recorded run above remains the warm measured result.

### Exact state and evidence checks

The canonical project retained exact, source-linked facts rather than inferred prose:

- `ian_wits > 0` at `scripts/script.rpy:244`.
- `ian_charisma > 0` at `scripts/script.rpy:246`.
- `ian_lena_mmf_points += 1` at `scripts/master_script.rpy:2256`.
- `ian_lena_dating = True` at `scripts/gallery/gallery_scene_setups.rpy:1103`.
- `chapter = 3` at `scripts/master_script.rpy:1994`.

Every checked fact had a non-null beat link.

### Archive immutability

Before and after values were identical:

| Property | Before and after |
| --- | --- |
| SHA-256 | `953fae213f32a9d0cae2432ef09924d2f9f83c960691f42a15b73cc747aade99` |
| Size | 70,031,252 bytes |
| LastWriteTimeUtc | `2026-07-10T17:11:44.0000000Z` |

The comparison passed independently for hash, size, and timestamp.

## Acceptance decision

All M04 acceptance criteria are satisfied:

- A Windows user can use the native shell to select/open a source or project without command-line
  interaction.
- The canonical project opens to a bounded view and never renders all beats or edges at once.
- `new_prologue` is an expandable 49-group container, not a 196-beat card or default 196-node
  view.
- Semantic zoom changes map level and information meaning, while fit preserves the active level.
- Choices expose options, exact requirements, known effects, and exact evidence.
- Large branches navigate independently with per-level view and selection state.
- Background workers keep the UI responsive, and cancellation/error paths preserve the project.
- No embedded game code ran, no game-directory write occurred, and the source archive remained
  unchanged.
- Integrated review, tests, lint, strict typing, environment, Qt workflow, and deterministic
  canonical checks passed.

## Limitations and deferred work

- Level 2 groups are deterministic four-beat structural slices. They are deliberately not claimed
  to be human-quality scenes or story summaries.
- The one-time v2-to-v3 presentation build took 136.324 seconds and expanded the copied canonical
  SQLite project to about 2.26 GB. Subsequent opening and bounded queries are much faster.
- The overview intentionally presents the first bounded page. Search exact-focus provides access
  to off-page matches; a general-purpose load-more browser was not required for M04.
- Broad substring searches with no result may scan many indexed search rows, but run in a
  background worker and return a bounded result set.
- Native `QGraphicsView` was selected instead of an embedded Cytoscape.js/ELK stack because it
  satisfied offline Windows behavior, the render cap, accessibility, and deterministic headless
  testing in this milestone.
- A final foreground automation rerun was stopped after two interrupted desktop-control attempts.
  The post-fix native Qt acceptance harness exercised the same `MainWindow`, controller, workers,
  and canvas against the copied canonical project and passed.
- AI organization, provider integration, natural-language questions, ending/route workflows,
  packaging, installers, releases, macOS, game editing, and patching remain excluded.

M05 can build opt-in AI organization and final product validation on this deterministic map, but
M05 has not been approved, scoped into a goal, or started.

## Artifacts

- `docs/milestones/M04/GOAL.md` - approved objective, deliverables, and acceptance criteria.
- `docs/milestones/M04/TASKS.md` - visible worker-task register and integration notes.
- `docs/milestones/M04/INFOGRAPHIC.png` - native-generated visual milestone summary.
- `artifacts/m04-acceptance/canonical-results.json` - canonical performance and deterministic
  query evidence; ignored by Git.
- `artifacts/m04-acceptance/canonical-ui-results.json` - canonical Qt workflow evidence; ignored
  by Git.
- `artifacts/m04-acceptance/archive-before.json` and `archive-after.json` - source archive
  immutability evidence; ignored by Git.
