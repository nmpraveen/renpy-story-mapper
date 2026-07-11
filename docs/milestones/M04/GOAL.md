# M04 Goal - Three-Level Windows Story Map

## Objective

Build the actual Windows application and prove that a complicated Ren'Py game can be explored
without displaying hundreds of equal-weight nodes at once.

## Deliverables

- PySide6 desktop shell for selecting a game folder or `scripts.rpa` archive and creating,
  opening, and refreshing durable projects.
- Responsive background analysis with progress, cancellation, clear errors, and consistent
  saved-project recovery.
- Interactive graph canvas with pan, zoom, fit, selection, and stable navigation.
- Three semantic detail levels with deterministic hierarchy from labels or chapters, through
  structural event groups, to exact beats and source evidence.
- Progressive expansion and virtualization so only visible or requested details render.
- Distinct deterministic presentation for story events, choices, gates, effects, merges, loops,
  shared calls, endings, technical content, and unresolved behavior.
- Requirement and effect badges with filters by variable and category.
- Search and source-evidence inspection.
- Persistent user controls for variable names and categories, node names, and hidden technical
  noise.
- Diagnostics and log presentation that avoids unnecessary exposure of original story content.
- Independent correctness and usability review of the integrated implementation.
- Complete Windows verification, completion report, and native-generated infographic.
- One M04 milestone PR, left unmerged pending explicit user approval.

## Acceptance criteria

- A Windows user can select the canonical archive, create or reopen its project, and reach a usable
  map without command-line work.
- Opening the canonical project never attempts to render all beats or edges simultaneously.
- The M02 `new_prologue` result is an expandable container, not one unreadable 196-beat card and
  not a 196-node default view.
- Zoom changes displayed semantic meaning and detail rather than only physical scale.
- Choices visibly show their options, requirements, and known effects.
- Selecting an overview or event item can reveal exact Level 3 source evidence.
- Large branches expand and collapse independently without losing position or selection.
- The UI remains responsive and cancellation leaves the saved project consistent.
- No operation writes to the game directory or archive or executes embedded game code.
- Every worker diff is inspected and integrated on the milestone branch.
- No critical correctness or usability review findings remain.
- Windows UI checks, pytest, Ruff, strict mypy, `pip check`, and M04 end-to-end checks pass on
  Windows CPython 3.12.
- The canonical archive SHA-256, size, and LastWriteTimeUtc are unchanged before and after access.
- `TASKS.md`, `COMPLETION_REPORT.md`, and native `INFOGRAPHIC.png` exist.
- The M04 PR is ready for user review and no M05 work has begun.

## Explicit exclusions

- No AI grouping, summarization, provider integration, or cloud story-text transfer.
- No chatbot, natural-language query, ending finder, or route-question workflow.
- No packaging, installer, release, public distribution, macOS, game editing, or game patching.

## State

Complete on 2026-07-10 on `milestone/m04-three-level-windows-map`. Self-goal task ID:
`019f4d73-853a-7df2-a43a-47733dbafb95`. All implementation, worker integration, independent
review, Windows verification, canonical acceptance, archive immutability checks, documentation,
and native infographic requirements passed. PR
[#6](https://github.com/nmpraveen/renpy-story-mapper/pull/6) is open and intentionally unmerged
for user approval. M05 has not started.
