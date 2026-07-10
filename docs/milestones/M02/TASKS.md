# M02 Task Register

Milestone branch: `milestone/m02-semantic-scenes`

Milestone base: `40f1bfa19ce6233b9dd781800e5e3ee943bb2c89`

Runtime authority: Windows with CPython 3.12

## Work packages

| Task ID | Title | Responsibility | Assigned branch/worktree | Owned files or subsystem | Status | Final commit |
| --- | --- | --- | --- | --- | --- | --- |
| `019f4d88-982d-7881-bf5d-6ad79d43bffc` | M02 - Semantic model and grouping engine | Semantic schema, deterministic grouping, structural boundaries, provenance, conservative classification | `worker/m02-semantic-engine`; `C:\Users\prave\.codex\worktrees\ee57\Renpy` | `src/renpy_story_mapper/semantic.py` | Complete and integrated | Worker `22f8488`, correction `0337303`; integrated as `f02b5d5` and `6b5fea9` |
| `019f4d88-982d-7881-bf5d-6af22b8f6c4e` | M02 - Fixtures and behavioral tests | Representative fixtures and behavioral contract tests | `worker/m02-semantic-tests`; `C:\Users\prave\.codex\worktrees\ce67\Renpy` | `tests/fixtures/semantic/`, `tests/test_semantic.py` | Complete and integrated | Worker `e4cef60`; integrated as `d2ffa71` |
| Pending creation | M02 - Independent correctness review | Review the integrated M02 diff for semantics, determinism, provenance, safety, and regressions | Separate Codex worktree from integrated milestone head | Review-only; no implementation files unless explicitly reassigned | Planned | - |

The orchestrator owns CLI integration, any changes outside the assigned worker files, conflict
resolution, full Windows acceptance, final documentation, the native infographic, and the M02 PR.

## Required worker return contract

Each worker must report status, branch and final commit, files changed, behavior or review findings,
exact test commands and results, known limitations, risks, unresolved questions, integration
instructions, and confirmation that it stayed within scope.

## Integration notes

- The first combined semantic contract run produced 7 failures and 1 pass because the engine and
  independent tests selected different public schemas.
- The orchestrator returned the mismatch to the engine worker without weakening the tests.
- Correction `0337303` aligned the projection while retaining deterministic provenance and safety.
- After orchestrator CLI integration, the integrated suite passed 42 tests on Windows.
