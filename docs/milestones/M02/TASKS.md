# M02 Task Register

Milestone branch: `milestone/m02-semantic-scenes`

Milestone base: `40f1bfa19ce6233b9dd781800e5e3ee943bb2c89`

Runtime authority: Windows with CPython 3.12

## Work packages

| Task ID | Title | Responsibility | Assigned branch/worktree | Owned files or subsystem | Status | Final commit |
| --- | --- | --- | --- | --- | --- | --- |
| `019f4d88-982d-7881-bf5d-6ad79d43bffc` | M02 - Semantic model and grouping engine | Semantic schema, deterministic grouping, structural boundaries, provenance, conservative classification | `worker/m02-semantic-engine`; `C:\Users\prave\.codex\worktrees\ee57\Renpy` | `src/renpy_story_mapper/semantic.py` | Complete and integrated | Worker `22f8488`, `0337303`, `0554492`, `bd9c358`; integrated as `f02b5d5`, `6b5fea9`, `699c969`, `8be37e3` |
| `019f4d88-982d-7881-bf5d-6af22b8f6c4e` | M02 - Fixtures and behavioral tests | Representative fixtures and behavioral contract tests | `worker/m02-semantic-tests`; `C:\Users\prave\.codex\worktrees\ce67\Renpy` | `tests/fixtures/semantic/`, `tests/test_semantic.py` | Complete and integrated | Worker `e4cef60`, `1e90881`; integrated as `d2ffa71`, `b89059c`; orchestrator regression `62acdfd` |
| `019f4d92-65df-7202-83b9-c5957d24c66c` | M02 - Independent correctness review | Review the integrated M02 diff for semantics, determinism, provenance, safety, and regressions | `review/m02-correctness`; `C:\Users\prave\.codex\worktrees\1793\Renpy` | Review-only; no implementation files unless explicitly reassigned | Complete; accepted on re-review | No commit; initial result: fix then re-review; final result: accept with no findings |

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
- Independent review at `0fe99e8` found three P1 defects and two P2 defects despite the green
  suite: merge-route loops, dropped call-continuation summaries, missing natural endings,
  multiline dialogue misclassification, and incomplete future-contract rejection.
- The implementation and test tasks were reopened; the same reviewer will inspect the corrected
  integrated head.
- Regression commit `1e90881` initially produced 7 expected failures; engine correction `0554492`
  closed five and exposed two final contract mismatches.
- Final correction `bd9c358` closed call-summary provenance and natural-ending transition gaps.
- Independent re-review of integrated head `8be37e3` found no remaining P0-P3 findings and
  recommended acceptance.
- The orchestrator added an explicit unknown-node regression in `62acdfd`; the final suite passed
  50 tests.
- Canonical-sample acceptance produced byte-identical manifest, graph, and semantic outputs across
  two runs while preserving the archive fingerprint.
- M02 pull request #3 is open and unmerged, stacked on M01 documentation PR #2.
