# M06 Worker Tasks

Milestone branch: `codex/m06-safe-ingestion-route-semantics`

Milestone base: `7b5deeeeeab35a358eb78b7b660d3d57c02717b2`

Normal worker model: GPT-5.6 Sol, High reasoning, fast mode disabled. M06 performs no Luna story
analysis.

| Task ID | Title | Responsibility | Branch | Status |
|---|---|---|---|---|
| Pending | M06 source ingestion and recovery | Unified discovery, precedence, isolated recovery, provenance, export, schema storage, focused tests | `codex/m06-source-recovery` | Preparing |
| Pending | M06 control-region semantics | Calls/returns, loops, post-dominators, regions, edge roles, persistence, fixtures | `codex/m06-control-regions` | Preparing |
| Pending | M06 security, fixtures, and review | Malicious/compatibility fixtures, migration/performance harness, independent review and new tests | `codex/m06-security-review` | Blocked until implementation contracts are available |

## Coordination rules

- Each worker edits only its assigned subsystem and returns a commit hash, diff summary, exact test
  commands/results, risks, and unresolved items.
- Workers do not edit `docs/MASTER_PLAN.md`, this milestone's orchestration files, provider/UI code,
  or future M07 behavior unless the orchestrator explicitly reassigns it.
- The orchestrator inspects and integrates every diff. Worker completion is not acceptance.
- Defective work is returned to its responsible task before final integration.
