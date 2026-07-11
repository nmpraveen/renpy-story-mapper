# M04 Task Register

Milestone branch: `milestone/m04-three-level-windows-map`

Milestone base: `0bb53ef88db3428a7e2625724496fad0f3506afd`

Runtime authority: Windows with CPython 3.12

## Work packages

| Task ID | Title | Responsibility | Assigned branch/worktree | Owned files or subsystem | Status | Final commit |
| --- | --- | --- | --- | --- | --- | --- |
| `019f4ec5-acb6-7043-ae45-a9026297c24b` | M04 - Bounded deterministic presentation model | Persistent bounded three-level queries, deterministic hierarchy, search/evidence, filters, overrides, migration and refresh consistency | `codex/m04-presentation-model`; `C:\Users\prave\.codex\worktrees\7d68\Renpy` | `presentation.py`; storage/project/project-analysis integration; presentation tests and fixtures | Active from base `85b907c` | Pending |
| `019f4ec5-acbe-74f2-8115-f6ae0381aea9` | M04 - Windows project lifecycle shell | PySide6 application shell, project selection/lifecycle, background work, cancellation, errors, diagnostics and integration hooks | `codex/m04-windows-shell`; `C:\Users\prave\.codex\worktrees\71fd\Renpy` | `pyproject.toml`; `ui/app.py`, `ui/main_window.py`, `ui/workers.py`, controller; shell tests and fixtures | Delivered, independently inspected, verified, and integrated | Worker `24ac0a6`; integrated `97d0d7c` |
| `019f4ec5-acb8-7830-89cf-ec6ad4a38856` | M04 - Virtualized semantic graph canvas | Local PySide6 graph canvas, bounded rendering, semantic zoom, navigation, selection, styling and evidence signals | `codex/m04-graph-canvas`; `C:\Users\prave\.codex\worktrees\0eb3\Renpy` | `ui/graph_canvas.py`; canvas tests and fixtures | Delivered; first diff rejected for encoding and stale selection; corrected, independently verified, and integrated | Worker `d152a3a` + `be32fba`; integrated `1bb5ef6` + `e54f975` |

The orchestrator owns cross-package architecture, integration, conflicts, the complete Windows
acceptance suite, canonical-sample verification, documentation, native infographic generation,
and the single M04 PR.

## Required worker return contract

Each worker must report its task ID, status, branch and worktree, final commit, files changed,
delivered behavior or findings, exact test commands and results, known limitations, risks,
unresolved questions, integration instructions, and confirmation that it stayed within scope.

## Integration notes

- M04 was explicitly approved on 2026-07-10 against the revised master plan.
- The M04 self-goal and milestone branch were created before implementation began.
- The Windows shell and graph canvas were independently rerun on the orchestrator branch. The
  first canvas delivery was returned for a visible-text encoding defect and stale-selection edge
  case; both were regression-tested before integration.
- M05 work remains excluded until M04 is complete and separately approved.
