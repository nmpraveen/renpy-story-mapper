# M03 Task Register

Milestone branch: `milestone/m03-story-state-projects`

Milestone base: `0451fbb3068aa4b548e51992c628977b149fb145`

Runtime authority: Windows with CPython 3.12

## Work packages

| Task ID | Title | Responsibility | Assigned branch/worktree | Owned files or subsystem | Status | Final commit |
| --- | --- | --- | --- | --- | --- | --- |
| `019f4e18-a30e-71e1-984e-decff4c61faf` | M03 - SQLite project persistence | Versioned schema, migrations, durable records, project lifecycle, incremental refresh, cancellation and recovery | `codex/m03-project-persistence`; `C:\Users\prave\.codex\worktrees\931a\Renpy` | Project persistence source plus `tests/test_project_storage.py` | Delivered; task-system error after file delivery; recovered, verified, and integrated | Worker `28118f0`; integrated `5168e25` |
| `019f4e18-a276-7e73-84f5-8e9649eb85b8` | M03 - Deterministic state extraction | Requirements, explicit effects, literal-argument calls, state registry and evidence/status model | `codex/m03-deterministic-state-extraction`; `C:\Users\prave\.codex\worktrees\8654\Renpy` | State-analysis source plus `tests/test_state_extraction.py` | Delivered; task-system error after file delivery; recovered, verified, and integrated | Worker `0a0ab6d`; integrated `2429405` |
| `019f4e18-a314-73e2-b8e5-14bf93425b48` | M03 - Fixtures and contract tests | Independent behavior contracts for persistence, incremental invalidation, state facts, unsafe cases and corruption | `codex/m03-contract-tests`; `C:\Users\prave\.codex\worktrees\dcf1\Renpy` | `tests/fixtures/m03/` and `tests/test_m03_contract.py` | Delivered and integrated; task-system error after commit | Worker `095814f`; integrated `e34c549` |
| `019f4e29-6b9b-7171-b5c5-23bf062358e3` | M03 - Independent correctness review | Review integrated M03 for persistence fidelity, invalidation, provenance, safety and regressions | `C:\Users\prave\.codex\worktrees\8fb0\Renpy` from integrated `9249857`; review branch assigned by Codex | Review-only unless explicitly reassigned | Active | Pending |

The orchestrator owns cross-module integration, CLI/diagnostic harness changes, conflicts, the
complete Windows acceptance suite, canonical-sample verification, documentation, native
infographic generation, and the M03 PR.

## Required worker return contract

Each worker must report its task ID, status, branch/worktree and final commit, files changed,
delivered behavior or findings, exact test commands and results, known limitations, risks,
unresolved questions, integration instructions, and confirmation that it stayed within scope.

## Integration notes

- M03 was explicitly approved on 2026-07-10 against the revised master plan.
- The revised plan and milestone control documents are included on the M03 branch before worker
  work begins.
- All three initial worker tasks encountered a Codex task-system error after producing their
  assigned files. The orchestrator inspected the intact worktrees, ran their focused checks,
  anchored each worker commit, and integrated the actual diffs rather than treating task status
  as completion proof.
