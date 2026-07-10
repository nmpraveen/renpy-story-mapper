# M03 Goal - Story State and Durable Projects

## Objective

Preserve analyses in reusable, versioned SQLite projects and add deterministic, source-linked
requirements and state effects so later map layers can explain why routes open and what choices
change.

## Deliverables

- Versioned SQLite schema with tested migrations.
- Durable storage for source fingerprints, the M01 graph, M02 semantic data, diagnostics,
  unresolved records, metadata, gates, effects, and state variables.
- Project create, open, refresh, and delete operations.
- Content-hash incremental refresh that skips unchanged sources and invalidates only dependent
  derived data.
- Safe deterministic extraction of simple requirements, assignments, increments, decrements,
  and visible literal-argument state-related calls.
- A state-variable registry with inferred category, original name, editable display name, and
  exact source evidence.
- Explicit proven, possible, and unresolved effect classifications.
- Safe temporary-file, cancellation, corruption, incompatible-version, and recovery behavior.
- Representative fixtures and contract tests for relationship points and flags, skills, money,
  jobs, progression gates, chained requirements, and unsupported dynamic cases.
- Independent correctness review of the integrated implementation.
- Complete Windows verification, completion report, and native-generated infographic.
- One M03 milestone PR, left unmerged pending explicit user approval.

## Acceptance criteria

- Closing and reopening preserves byte-equivalent authoritative graph, semantic, gate, and effect
  data.
- Refreshing unchanged content does not reparse unchanged sources.
- Changing one source invalidates only data that depends on that source.
- Literal examples such as `love += 1`, `dating = True`, `job = "Company Z"`, and `wits > 0`
  retain exact physical-line evidence and correct proven or unknown status.
- The canonical archive captures Wits and Charisma gates plus representative point or flag
  changes without executing game code.
- Dynamic or unsafe expressions remain unresolved and are never promoted to proven effects.
- Full canonical analysis writes nothing beside the archive and records elapsed time and
  peak-scale counts.
- Database corruption and incompatible schema versions fail safely.
- Every worker diff is inspected and integrated on the milestone branch.
- No critical correctness-review findings remain.
- Pytest, Ruff, strict mypy, `pip check`, and M03 end-to-end checks pass on Windows CPython 3.12.
- The canonical archive fingerprint, size, and LastWriteTimeUtc are unchanged before and after
  access.
- `TASKS.md`, `COMPLETION_REPORT.md`, and native `INFOGRAPHIC.png` exist.
- The M03 PR is ready for user review and no M04 or M05 work has begun.

## Explicit exclusions

- No desktop UI beyond a minimal diagnostic harness.
- No AI grouping, summarization, or provider work.
- No packaging or installer work.

## State

Active as of 2026-07-10 after explicit user approval. Implementation and verification are in
progress on `milestone/m03-story-state-projects`.
