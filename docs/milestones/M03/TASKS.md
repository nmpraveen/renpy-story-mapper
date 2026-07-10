# M03 Task Register

Milestone branch: `milestone/m03-story-state-projects`

Milestone base: `0451fbb3068aa4b548e51992c628977b149fb145`

Runtime authority: Windows with CPython 3.12

## Work packages

| Task ID | Title | Responsibility | Assigned branch/worktree | Owned files or subsystem | Status | Final commit |
| --- | --- | --- | --- | --- | --- | --- |
| `019f4e18-a30e-71e1-984e-decff4c61faf` | M03 - SQLite project persistence | Versioned schema, migrations, durable records, project lifecycle, incremental refresh, cancellation and recovery | `C:\Users\prave\.codex\worktrees\931a\Renpy` from milestone base; worker branch assigned by Codex | Project persistence source plus `tests/test_project_storage.py` | Active | Pending |
| `019f4e18-a276-7e73-84f5-8e9649eb85b8` | M03 - Deterministic state extraction | Requirements, explicit effects, literal-argument calls, state registry and evidence/status model | `C:\Users\prave\.codex\worktrees\8654\Renpy` from milestone base; worker branch assigned by Codex | State-analysis source plus `tests/test_state_extraction.py` | Active | Pending |
| `019f4e18-a314-73e2-b8e5-14bf93425b48` | M03 - Fixtures and contract tests | Independent behavior contracts for persistence, incremental invalidation, state facts, unsafe cases and corruption | `C:\Users\prave\.codex\worktrees\dcf1\Renpy` from milestone base; worker branch assigned by Codex | `tests/fixtures/m03/` and `tests/test_m03_contract.py` | Active | Pending |
| Pending | M03 - Independent correctness review | Review integrated M03 for persistence fidelity, invalidation, provenance, safety and regressions | Review worktree created after integration | Review-only unless explicitly reassigned | Not started | Pending |

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
