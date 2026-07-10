# M03 Task Register

Milestone branch: `milestone/m03-story-state-projects`

Milestone base: `0451fbb3068aa4b548e51992c628977b149fb145`

Runtime authority: Windows with CPython 3.12

## Work packages

| Task ID | Title | Responsibility | Assigned branch/worktree | Owned files or subsystem | Status | Final commit |
| --- | --- | --- | --- | --- | --- | --- |
| Pending | M03 - SQLite project persistence | Versioned schema, migrations, durable records, project lifecycle, incremental refresh, cancellation and recovery | Codex worktree from milestone base | Project persistence source plus focused storage tests | Creating | Pending |
| Pending | M03 - Deterministic state extraction | Requirements, explicit effects, literal-argument calls, state registry and evidence/status model | Codex worktree from milestone base | State-analysis source plus focused extraction tests | Creating | Pending |
| Pending | M03 - Fixtures and contract tests | Independent behavior contracts for persistence, incremental invalidation, state facts, unsafe cases and corruption | Codex worktree from milestone base | M03 fixtures and black-box acceptance tests | Creating | Pending |
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
