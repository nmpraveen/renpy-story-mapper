# M04 Task Register

Milestone branch: `milestone/m04-three-level-windows-map`

Milestone base: `0bb53ef88db3428a7e2625724496fad0f3506afd`

Runtime authority: Windows with CPython 3.12

## Work packages

| Task ID | Title | Responsibility | Assigned branch/worktree | Owned files or subsystem | Status | Final commit |
| --- | --- | --- | --- | --- | --- | --- |
| `019f4ec5-acb6-7043-ae45-a9026297c24b` | M04 - Bounded deterministic presentation model | Persistent bounded three-level queries, deterministic hierarchy, search/evidence, filters, overrides, migration and refresh consistency | `codex/m04-presentation-model`; `C:\Users\prave\.codex\worktrees\7d68\Renpy` | `presentation.py`; storage/project/project-analysis integration; presentation tests and fixtures | Delivered; first diff returned for stale-index invalidation and event-title/rename search gaps; corrected, independently verified, and integrated | Worker `77d6089` + `db908fb`; integrated `8bf3087` + `956b09e` |
| `019f4ec5-acbe-74f2-8115-f6ae0381aea9` | M04 - Windows project lifecycle shell | PySide6 application shell, project selection/lifecycle, background work, cancellation, errors, diagnostics and integration hooks | `codex/m04-windows-shell`; `C:\Users\prave\.codex\worktrees\71fd\Renpy` | `pyproject.toml`; `ui/app.py`, `ui/main_window.py`, `ui/workers.py`, controller; shell tests and fixtures | Delivered, independently inspected, verified, and integrated | Worker `24ac0a6`; integrated `97d0d7c` |
| `019f4ec5-acb8-7830-89cf-ec6ad4a38856` | M04 - Virtualized semantic graph canvas | Local PySide6 graph canvas, bounded rendering, semantic zoom, navigation, selection, styling and evidence signals | `codex/m04-graph-canvas`; `C:\Users\prave\.codex\worktrees\0eb3\Renpy` | `ui/graph_canvas.py`; canvas tests and fixtures | Delivered; first diff rejected for encoding and stale selection; corrected, independently verified, and integrated | Worker `d152a3a` + `be32fba`; integrated `1bb5ef6` + `e54f975` |
| `019f4ef9-2881-71f2-aa00-2d7c43e6349f` | M04 - Independent Windows map contract and UI review | Independent acceptance-criteria review, adversarial contract tests, Windows suite, and P0-P3 findings | `codex/m04-independent-review`; `C:\Users\prave\.codex\worktrees\b7af\Renpy` | New review tests/fixtures only; production changes explicitly excluded | Delivered after three corrective review cycles; final review found no remaining P0-P3 issues | Worker test `19a3a41`; integrated `409a88b` |

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
- The presentation model's first delivery was returned because its derived-index generation was
  not authoritative and Level 2/current renamed titles were not searchable. Both defects received
  focused regression tests before integration.
- Independent review first found incomplete choice effects, non-point child lookups, lost
  cross-level selection, unpresented variable display names, and missing control-flow styles. A
  second pass found full descendant evidence/fact scans, and a third verified the corrected
  source-edge choice traversal. All findings were regression-tested; the final review passed 132
  tests with no remaining P0-P3 findings on its reviewed head.
- The canonical rendered walkthrough then exposed an off-page search focus gap after the formal
  review. Commit `6489985` added a bounded exact-focus slice and a 100-label regression; the final
  canonical Qt harness reached `new_prologue`, its 49 event groups, a choice with requirements and
  effects, and exact Level 3 evidence without rendering the full project.
- M05 work remains excluded until M04 is complete and separately approved.
