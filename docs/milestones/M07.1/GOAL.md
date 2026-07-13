# M07.1 — Safety and Real-Project Closure

## Objective

Close the verified M07 correctness, privacy, and real-browser gaps while preserving the local-first
Windows product and deterministic route authority.

## Deliverables

- Recovered-source transmission block and explicit acknowledgement enforced at prepare and
  immediately before provider invocation.
- Exact prepared-scope consent with conservative aggregate call, token, and time budgets.
- Serializer-aware deterministic prompt partitioning below 48,000 characters for normal and repair
  requests, with resumable cancellation and incremental accounting.
- Generation-safe drafts, accepted overlays, corrections, pins, claims, and refresh invalidation.
- Real evidence/detail schema alignment with exact qualified source-line navigation.
- Arbitrary route lanes and truthful cross-page continuation rendering.
- Honest asynchronous refresh completion reporting.
- Live Chrome → loopback server → real `ProjectApi` → temporary SQLite acceptance, without provider
  or remote calls and without production mock-project dependence.
- Full Windows quality gates, independent review, completion report, native infographic, and one
  unmerged pull request.

## Acceptance criteria

1. Blocked recovered source cannot be prepared or transmitted without a valid persisted
   acknowledgement, and the pre-provider check cannot be bypassed by stale prepared state.
2. Consent and budgets are bound to the exact generation and scope set; normal browser requests
   have finite defaults and deterministic rejection at their boundary.
3. Every serialized normal and repair request is below 48,000 characters, including the M07 route
   fixture; cancellation/resume and cache replay preserve validated work and accounting.
4. Refresh prevents stale assemblies from applying or overlaying changed deterministic data;
   claims, corrections, and pins survive and are presented where valid.
5. Real source lines, line basis, reconstructed provenance, and evidence display without mock-only
   fields.
6. Generated lane IDs determine layout; forks, merges, loops, terminals, gates, and page-boundary
   continuations remain visible and truthful.
7. The browser reports refresh success only after completion.
8. Live Chrome acceptance uses the loopback server and a temporary real SQLite project at 100% and
   200% zoom, makes no provider/remote request, and production assets do not expose mock mode.
9. Windows CPython 3.12 pytest, Ruff, strict mypy, `pip check`, `git diff --check`, wheel inspection,
   milestone end-to-end checks, and independent review complete with no unresolved P0–P2 finding.
10. `COMPLETION_REPORT.md` and native `INFOGRAPHIC.png` exist; the single M07.1 PR remains unmerged.

## Exclusions

- No live full-game Luna run, LM Studio, installer, hosted service, canonical archive access,
  analyzer rewrite, legacy desktop deletion, or storage consolidation.
