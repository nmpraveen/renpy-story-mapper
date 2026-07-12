# M06.5 Goal — Local Browser Interface Bridge

Status: Active

Base commit: `00216509e7b478a8e284b6fe18d399e088e2d6e6`

Branch: `codex/m06-5-local-web-interface`

## Objective

Make a secure, locally served browser interface the primary Windows UI while preserving the
existing local analysis engine, read-only source handling, deterministic authority, project
storage, and explicit AI consent boundary.

## Deliverables

- Loopback-only authenticated local web launcher and typed API.
- Secure native Windows source/project selection.
- Browser parity for the current welcome, project lifecycle, Story Explorer, inspector/evidence,
  search/filter/navigation, progress/cancel, organization review, diagnostics, and settings flows.
- Polished accessible responsive interface with bounded graph rendering.
- Legacy PySide6 fallback using the same backend services.
- Automated API/security/UI tests, Chrome acceptance, independent review, report, and infographic.

## Acceptance criteria

- Full Windows CPython 3.12 pytest, Ruff, strict mypy, `pip check`, and whitespace checks pass.
- Chrome end-to-end acceptance passes at 100% and 200% zoom.
- Loopback/session/origin/CSRF/CSP/body/path/error controls pass adversarial tests.
- No game execution or writes, remote story transmission, implicit provider calls, or JavaScript
  duplication of deterministic authority.
- Project reopen, cancellation, bounded rendering, and exact evidence traversal pass.
- Independent review has no unresolved P0-P2 or accepted P3 correctness/security issue.
- Completion report, native infographic, and one M06.5 PR exist; the PR remains unmerged.
- M07 is not started.

## Exclusions

No hosted service, remote access, accounts, telemetry, installer, public release, M07 redesign,
parallel AI, LM Studio, full-game AI rerun, or analyzer rewrite.
