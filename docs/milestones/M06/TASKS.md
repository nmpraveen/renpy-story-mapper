# M06 Worker Tasks

Milestone branch: `codex/m06-safe-ingestion-route-semantics`

Milestone base: `7b5deeeeeab35a358eb78b7b660d3d57c02717b2`

Normal worker model: GPT-5.6 Sol, High reasoning, fast mode disabled. M06 performs no Luna story
analysis.

| Task ID | Title | Responsibility | Branch | Status |
|---|---|---|---|---|
| `019f56ee-f096-70a2-8153-4b78baa8e3f7` | M06 source ingestion and recovery | Unified discovery, precedence, isolated recovery, provenance, export, schema storage, focused tests | `codex/m06-source-recovery` | Complete: delivered `0e7cd8a`; integrated as `6ecc2dd` after scope-drift cleanup |
| `019f56ee-f096-70a2-8153-4b5bc768eb46` | M06 control-region semantics | Calls/returns, loops, post-dominators, regions, edge roles, persistence contract, fixtures | `codex/m06-control-regions` | Complete: `64adaab`, `9f025e1`, `0384ca3`, `1b3441c`; integrated as `0c18293`, `1611725`, `848b3c6`, `eb850dc` |
| `019f5712-5e51-7a81-9e78-4ac5815df620` | M06 security, fixtures, and review | Malicious/compatibility fixtures, migration/performance harness, independent review and new tests | `codex/m06-security-review` | Complete: review `8cc1e1a`; re-reviews `eb8dfe9` and `0f55d8d`; final SHIP with no P0-P3 findings |
| `019f56ef-a42f-7c92-a30f-e2b4c2b1e73a` | Duplicate control-region task | Accidental duplicate created by delayed worktree setup; no deliverables accepted | Unassigned | Cancelled and archived before integration |
| `019f56ef-ff5e-7153-99b8-7935a4f0077b` | Duplicate control-region task | Second delayed duplicate from the same worktree-registration race; no deliverables accepted | Unassigned | Cancelled and archived before integration |

## Coordination rules

- Each worker edits only its assigned subsystem and returns a commit hash, diff summary, exact test
  commands/results, risks, and unresolved items.
- Workers do not edit `docs/MASTER_PLAN.md`, this milestone's orchestration files, provider/UI code,
  or future M07 behavior unless the orchestrator explicitly reassigns it.
- The orchestrator inspects and integrates every diff. Worker completion is not acceptance.
- Defective work is returned to its responsible task before final integration.
