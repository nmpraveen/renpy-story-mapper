# M05 Goal - AI-Organized Story Explorer and Final Product Validation

## Objective

Convert the technically correct M04 graph into the finished Windows story-reading experience: a
polished, arc-first Story Explorer whose optional AI organization remains constrained by, and fully
traceable to, the immutable deterministic M01-M04 foundation.

## Deliverables

- Transactional schema v4 storage for organization runs, chunks, drafts, accepted arcs/events,
  quotient edges, claims and evidence, cache records, and durable user edits.
- Provider-neutral organization contracts plus one isolated `CodexCliProvider`; M05 exposes only
  the user's ChatGPT/Codex login with explicit GPT-5.6 Luna, High reasoning, and fast mode disabled.
  The existing LM Studio adapter remains dormant for later work.
- Manual organization only, fresh consent before every cloud run, rich-evidence safeguards,
  read-only ephemeral execution, strict output validation, cancellation, sanitized errors, and
  deterministic fallback.
- Evidence-aware chunking and reconciliation with a 48,000-character/120-beat target, two-beat
  context overlap, one repair retry, locally derived graph edges, and no invented authority.
- Deterministic left-to-right layered layout with stable strongly connected component collapse,
  ranking, crossing reduction, and branch lanes.
- Polished adaptive Windows light/dark welcome and three-pane arc-first workspace, semantic Levels
  1-3, review-before-apply, accessible keyboard navigation, and contextual corrections.
- Durable rename, split, merge, move, hide, pin, approve, and reject operations that override later
  AI results without changing authoritative connectivity.
- User-visible bounded worker tasks, inspected diffs, staged integration, and final adversarial
  review.
- Full Windows CPython 3.12 verification, complex synthetic fixture cloud validation, a separately
  consented small real-script smoke run, archive-safety evidence when applicable, and
  database-growth measurements. LM Studio and full canonical AI-scale validation are deferred.
- M05 completion report, required UI screenshots, native-generated infographic, and one unmerged
  M05 pull request.

## Acceptance criteria

- Level 1 contains no more than 12 coherent accepted arcs or turning points.
- Canonical `new_prologue` becomes 8-20 coherent events rather than one 196-beat scene.
- A selected arc defaults to no more than 30 Level 2 event cards and never exceeds the 240-item
  rendering cap.
- Level 3 preserves exact dialogue, expressions, relative source paths, and physical lines.
- Canonical choices, Wits/Charisma gates, representative relationship-point changes, dating flag,
  and chapter progression remain attached to the correct deterministic paths.
- Deterministic graph, requirement, effect, and evidence hashes are unchanged by organization.
- Every accepted AI event and interpretive claim references existing beat/evidence IDs; unsupported
  causal claims are labeled as interpretation or rejected.
- The user can move from arc to a choice, its requirement/effect, and exact evidence within three
  primary interactions.
- Provider failure or disabled AI leaves a usable deterministic layered map and never damages the
  accepted organization.
- Cancellation returns within two seconds without changing the accepted map.
- An unchanged rerun uses cache entries and launches no model subprocesses.
- Reopening restores accepted organization, corrections, filters, selection, and navigation without
  analysis or provider calls.
- Cloud transmission remains blocked until fresh confirmation for that run. Every live acceptance
  call explicitly uses GPT-5.6 Luna with High reasoning and fast mode disabled; unavailability or
  conflicting reported model metadata fails closed without changing the accepted map. When Codex
  omits redundant model metadata, the locked CLI model argument remains authoritative.
- The complex branching fixture is the primary AI acceptance source, and the small readable `.rpy`
  script is the secondary real-script smoke source. LM Studio and full canonical-game AI
  organization are recorded as deferred limitations rather than accepted behavior.
- The canonical archive's SHA-256, size, and LastWriteTimeUtc remain unchanged.
- Pytest, Ruff, strict mypy, `pip check`, Windows UI checks, and M05 end-to-end tests pass under
  Windows CPython 3.12.
- Independent review leaves no unresolved P0-P2 finding and no accepted P3 correctness/security
  finding.
- `TASKS.md`, `COMPLETION_REPORT.md`, required screenshots, and native `INFOGRAPHIC.png` exist, and
  the single M05 PR is ready but unmerged.

## Explicit exclusions

- No M06 or separate advanced-exploration milestone.
- No chatbot, natural-language story questions, or automatic ending finder.
- No installer, packaging, portable report, public release, or macOS support.
- No game editing, patching, embedded game execution, or unauthorized cloud transmission.
- No base-project compaction acceptance gate; record storage growth and defer optimization.

## State

Complete. The implementation was merged by the user through PR #7 at `2df4d67`; final synthetic
and separately consented real-script acceptance passed without changing deterministic authority or
the read-only source. Windows verification, completion documentation, retained screenshots, and
the native infographic are complete. The app currently exposes no active goal record after the
earlier product-level pause, so `GOAL.md` is the durable milestone-goal status.
