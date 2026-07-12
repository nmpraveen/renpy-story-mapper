# M06.5 Completion Report — Local Browser Interface Bridge

Date: 2026-07-12

Status: Complete; the milestone PR is published and must remain unmerged until explicit approval.

Milestone branch: `codex/m06-5-local-web-interface`

Baseline: `00216509e7b478a8e284b6fe18d399e088e2d6e6`

## Outcome

M06.5 makes a polished browser interface the primary presentation shell while keeping analysis,
projects, source access, and optional AI execution inside the existing Windows Python process. The
browser is not a hosted application: a launcher binds an authenticated service to exact IPv4
`127.0.0.1` on an ephemeral port, opens the local page, and shuts it down through an explicit Quit
flow.

The milestone intentionally preserves the current three presentation levels. The requested
two-level flowchart and resumable parallel AI design remain M07 work and were not implemented
early.

## Delivered behavior

### Local browser shell

- Added the `renpy-story-mapper-web` Windows entry point and module launcher.
- Packaged nine local browser assets; no Node runtime, CDN, remote font, analytics, or hosted
  dependency is required.
- Added Welcome, recent projects, native source/project selection, create, open, reopen, refresh,
  progress, cancellation, diagnostics, and explicit Quit flows.
- Retained the PySide6 interface as a legacy fallback and as the narrow native Windows dialog
  boundary; analysis logic was not duplicated in JavaScript.

### Story Explorer parity

- Added bounded Arc → Event → Evidence views with deterministic nodes and edges, pan, zoom, fit,
  keyboard selection, search, filters, facts, inspector, and direct evidence traversal.
- Browser rendering remains bounded to 80 nodes, 120 edges, and 240 presentation items.
- The unresolved filter now uses semantic authority joined by deterministic graph-node IDs and
  propagates through stored evidence/event/scene parentage. It does not infer story state from card
  labels.
- Layout and review lists remain bounded; an 85-candidate draft uses 40 rows per page and only five
  rows on page three.

### Organization review

- Added pending-only draft envelopes containing authoritative candidate groups and persisted
  decisions.
- Added one exact review mutation for explicit arc/event approval or rejection.
- Apply remains disabled and the API rejects application until every candidate has an explicit
  decision. No default or bulk approval was introduced.
- Open and render paths construct no provider and send no story text anywhere.

### Security and lifecycle

- Exact `127.0.0.1` binding, exact Host, loopback Origin, per-launch session, and CSRF validation.
- Restrictive CSP and security headers, no-store responses, local-only assets, bounded JSON bodies,
  static traversal rejection, opaque picker identifiers, and sanitized path-free errors.
- Atomic LocalAppData state updates and path-free routine browser responses.
- Every response closes its HTTP connection; request threads cannot block shutdown. Explicit Quit
  closes the browser service, executor, and native Qt bridge without leaving an orphan process.
- No game/Ren'Py Python was executed, no game/source file was modified, and the canonical sample
  archive was not accessed.

## Worker tasks and integration

| Task | Delivered work | Integration/result |
|---|---|---|
| Local web service/API `019f5758-498c-7c33-aeb6-1930b94f0a2f` | Secure server, API, launcher, lifecycle, authority classification, focused tests | Integrated as `205f1f3`, `85cc200`, `9a4c6a6`, `372fe6e` |
| Browser Story Explorer `019f5758-4997-73d3-b141-35d6bdf0486d` | Packaged UI, graph, project flows, review workflow, browser harness | Integrated as `d2a00e3`, `8278ea6`, `1d1cd98` |
| Independent review `019f5776-0862-73e1-baa2-e02cc2642ffb` | Four adversarial regressions and final security/API/UI/packaging report | PASS/SHIP integrated as `2316bbf` |

A duplicate review setup task (`019f5775-d43f-7aa0-849b-de26c49a651e`) was stopped and archived
before edits. Its cancelled status remains recorded in `TASKS.md`.

The independent review initially found broken create/refresh integration, an incomplete draft-review
contract, and a false-negative dynamic-jump classification. Each issue was reproduced, returned to
its responsible worker, corrected, and independently re-tested before acceptance.

## Windows verification

Runtime authority: Windows CPython 3.12.

Baseline before implementation:

```text
python -m pytest -q                         exit 0 — 376 passed
python -m ruff check src tests scripts      exit 0
python -m mypy src/renpy_story_mapper       exit 0 — 42 source files
python -m pip check                         exit 0
```

Final orchestrator acceptance after authority correction:

```text
python -m pytest -q                         exit 0 — 403 passed in 30.15s
focused web/API/frontend tests              exit 0 — 27 passed in 7.85s
python -m ruff check src tests scripts      exit 0
python -m mypy src/renpy_story_mapper       exit 0 — 49 source files
python -m pip check                         exit 0
git diff --check                            exit 0
```

One preceding full run had only the existing 10,000-node timing assertion exceed its 2.000-second
cutoff by 0.011 seconds while 402 other tests passed. The benchmark was not weakened: it passed in
1.95 seconds in isolation, and the immediate complete rerun passed all 403 tests.

Final independent review after adding four review regressions:

```text
full Windows suite                          exit 0 — 407 passed in 31.12s
independent regressions                     exit 0 — 4 passed in 3.10s
Ruff / strict mypy / pip check / diff       exit 0
recommendation                              PASS / SHIP
remaining P0 / P1 / P2                     none / none / none
```

The final closeout rerun after integrating the independent tests, completion documentation, and
native infographic passed all 407 tests in 32.24 seconds. Ruff, strict mypy across 49 source files,
`pip check`, and `git diff --check` all exited 0.

## Chrome verification

The final nine-state Chrome acceptance completed Welcome, Create, Refresh, Progress, Events at
100% and 200%, Evidence, Review, and 85-candidate Review Pages:

- all nine states exited 0;
- remote requests: 0;
- production Node runtime: false;
- create used the opaque project-save selection ID;
- refresh was invoked once and completed;
- direct evidence resolved to `evidence-1-e0`;
- the 85-candidate review persisted 85 explicit decisions and page three rendered five rows; and
- every state stayed inside the 240-item presentation boundary.

An additional actual production Chrome session used the real loopback service and completed create
and refresh with HTTP 200 responses. Explicit Quit was verified to remove its listener and both
launcher/runtime processes.

Closeout browser evidence is under
`C:\Users\prave\AppData\Local\Temp\rsm-m06-5-browser-closeout` and is not committed.

## Packaging

- `pip wheel . --no-deps`: exit 0.
- Wheel members: 75.
- Packaged browser assets: 9.
- Required web entry point: present.
- Independent clean-build reproducibility: two byte-identical wheels, 290,875 bytes, SHA-256
  `46189715ce1e5e212cc0d59e3d872da4f7e0d6b4ae9f66af81db767d69608ff2`.
- Final orchestrator wheel inspection also passed with all nine assets and all three console entry
  points present.

## Limitations and deferred work

- This bridge retains the current Arc → Event → Evidence model. M07 is responsible for the broad
  Route Map plus detailed Evidence view requested by the user.
- The service is intentionally local-only. There is no hosted deployment, remote access, account
  system, telemetry, installer, or public release.
- Native dialogs were exercised with deterministic narrow adapters in automated Chrome acceptance;
  the Qt implementations were inspected and their picker contracts tested.
- Cancelling the destination picker currently shows a harmless error toast instead of returning
  silently. Chrome also logs harmless noise for a duplicate meta `frame-ancestors` directive and a
  missing favicon. Independent review classified both as non-blocking P3 polish.
- No provider-backed organization run, parallel AI, LM Studio work, or full-game AI rerun occurred.

## Required artifacts

- Goal: `docs/milestones/M06.5/GOAL.md`
- Task ledger: `docs/milestones/M06.5/TASKS.md`
- Independent review: `docs/milestones/M06.5/INDEPENDENT_REVIEW.md`
- Completion report: this file
- Native infographic: `docs/milestones/M06.5/INFOGRAPHIC.png`
- Pull request: https://github.com/nmpraveen/renpy-story-mapper/pull/10 (unmerged)
