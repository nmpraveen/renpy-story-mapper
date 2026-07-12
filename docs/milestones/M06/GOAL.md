# M06 Goal — Safe Source Recovery and Correct Route Semantics

Status: Active

Base commit: `7b5deeeeeab35a358eb78b7b660d3d57c02717b2`

Branch: `codex/m06-safe-ingestion-route-semantics`

## Objective

Accept common modern Ren'Py source forms without modifying or executing the game, and add a
deterministic control-region layer that distinguishes temporary detours, persistent routes, loops,
merges, terminals, and unresolved behavior before presentation or AI organization.

## Deliverables

- Unified read-only ingestion for game folders, `.rpy`, `.rpyc`, `.rpa`, and existing projects.
- Existing bounded RPA reader retained; isolated pinned Unrpyc runtime for compiled-source recovery.
- Qualified reconstructed-source provenance, safe caching, explicit export, and schema-v5 storage.
- Procedure summaries, loop classification, post-dominators, control regions, ownership, edge
  roles, and terminal classification.
- Deterministic fixtures, migration/security/performance tests, integration documentation, and an
  independent review.
- `COMPLETION_REPORT.md` and native `INFOGRAPHIC.png` after final Windows acceptance.

## Acceptance criteria

- Windows CPython 3.12 full pytest, Ruff, strict mypy, `pip check`, `git diff --check`, and all M06
  end-to-end checks pass.
- Recovery never executes game code, writes beside the game, or weakens existing bounded archive
  protections; timeout, cancellation, malformed input, ambiguity, cache, provenance, and export
  cases pass.
- Reconvergent alternatives never create persistent route boundaries; persistent state dispatch or
  distinct terminals remain distinct; calls, returns, loops, and unresolved behavior remain exact.
- Every authoritative transition retains evidence and a semantic role or unresolved diagnostic.
- Stable IDs and byte-equivalent deterministic output survive input permutations and reopen.
- The ~10k-node performance fixture completes control analysis within two seconds and under 256 MB
  additional peak memory on the acceptance machine.
- Any accessed read-only sample retains identical SHA-256, size, and `LastWriteTimeUtc`.
- All worker diffs are inspected, one M06 PR is opened and left unmerged, the master plan and
  completion report are updated, and the native infographic exists before this goal is completed.

## Exclusions

- No M07 UI or parallel-AI implementation.
- No LM Studio work, installer, public release, macOS work, executable/APK/ZIP scanning, legacy
  Python 2 recovery, game editing, or automatic cloud story transmission.
