# M02 Task Register

Milestone branch: `milestone/m02-semantic-scenes`

Milestone base: `40f1bfa19ce6233b9dd781800e5e3ee943bb2c89`

Runtime authority: Windows with CPython 3.12

## Work packages

| Task ID | Title | Responsibility | Assigned branch/worktree | Owned files or subsystem | Status | Final commit |
| --- | --- | --- | --- | --- | --- | --- |
| Pending creation | M02 - Semantic model and grouping engine | Semantic schema, deterministic grouping, structural boundaries, provenance, conservative classification | Separate Codex worktree from milestone base | `src/renpy_story_mapper/semantic.py` and directly related new semantic-model modules only | Planned | - |
| Pending creation | M02 - Fixtures and behavioral tests | Representative fixtures and behavioral contract tests | Separate Codex worktree from milestone base | `tests/fixtures/semantic/`, `tests/test_semantic.py` | Planned | - |
| Pending integration | M02 - Independent correctness review | Review the integrated M02 diff for semantics, determinism, provenance, safety, and regressions | Separate Codex worktree from integrated milestone head | Review-only; no implementation files unless explicitly reassigned | Planned | - |

The orchestrator owns CLI integration, any changes outside the assigned worker files, conflict
resolution, full Windows acceptance, final documentation, the native infographic, and the M02 PR.

## Required worker return contract

Each worker must report status, branch and final commit, files changed, behavior or review findings,
exact test commands and results, known limitations, risks, unresolved questions, integration
instructions, and confirmation that it stayed within scope.
