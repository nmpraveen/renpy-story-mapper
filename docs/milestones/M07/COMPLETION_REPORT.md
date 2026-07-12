# M07 Completion Report — Two-Level Route Map and Resumable Parallel AI

Date: 2026-07-12

Status: Complete; the single M07 pull request is published and remains unmerged pending explicit
user approval.

Milestone branch: `codex/m07-two-level-route-map`

Baseline: `e24509c87b95a6584546a3c2ad9cbffaa1cdaf4c` (M06.5 merged through PR #10)

## Outcome

M07 replaces the previous three-level card hierarchy with exactly two visible levels: a broad,
line-first Route Map and one Detail/Evidence workspace. It also adds a consent-gated, checkpointed
parallel organization engine whose mocked provider contract is locked to GPT-5.6 Luna, High
reasoning, with fast mode disabled.

Deterministic analysis remains authoritative for every source-linked edge, gate, effect, detour,
persistent route, merge, loop, unresolved target, and terminal. AI can only name, summarize, and
interpret existing evidence. Opening, rendering, paging, and preparing organization construct no
provider and transmit no story text.

## Delivered behavior

### Two-level story exploration

- A chronological spine is the primary visual grammar, with compact stations connected by lines.
- Reconvergent detours return to a shared point instead of being counted as distinct persistent
  branches.
- Persistent choices keep stable route lanes; proven merges, loops, update boundaries, dead ends,
  route endings, game endings, and unresolved dynamic targets remain distinct.
- Gates appear on entering paths and effects on the station or path that causes them.
- Technical-only runs collapse into coverage corridors rather than walls of singleton boxes.
- Any station or line opens the same Detail/Evidence workspace directly; there is no third level.
- Exact relative source paths and physical-line evidence remain available in detail.

### Bounded browser map

- The default page contains no more than 30 nodes, 180 line segments, or 240 combined items.
- Dense pages preserve complete topology through independent node and edge cursors. The final
  adversarial sequence exercised `0:0 → 0:180 → 0:0 → 0:180` across 195 line segments.
- Search, filters, selection, pan, zoom, fit, keyboard navigation, and direct evidence traversal do
  not change semantic level.
- The local browser shell retains create/open/refresh, diagnostics, settings, Quit, loopback-only
  security, opaque picker IDs, no remote assets, and no Node runtime requirement.

### Resumable parallel organization

- Pre-AI route scopes are deterministic and durable.
- Provider work starts with eight workers and can ramp to twelve; repairs are capped at two
  concurrent requests.
- Rate limits, latency, errors, soft time/token targets, and hard budgets adapt concurrency,
  timeout, and fallback behavior.
- Each provider attempt persists call/token usage immediately.
- Checkpoints support pending, cached/in-flight, validated, fallback, failed, and cancelled states.
- Validated scopes survive cancellation and resume; identical replay can complete with zero
  provider calls.
- Final assembly is serialized by scope ordinal and ID, so worker completion order cannot change
  output.
- The browser reports calls, tokens, ETA ranges, and separate AI-versus-technical coverage, and it
  supports review/apply of validated partial results.

## Synthetic acceptance authority

The M07 fixture is synthetic and source-controlled:

- `route_topology.rpy`: 103 physical lines; SHA-256
  `43df511d48e75dba2314e8df6f01ec5174b932e37668ae6db5c27f617ca741e5`.
- Baseline deterministic output: 97 graph nodes, 106 graph edges, 14 labels/scenes, 64 semantic
  beats, 79 transitions, 5 requirements, 14 effects, 13 state variables, and 1 unresolved target.
- It includes three local detours, two terminal splits, one loop, two persistent routes, shared call
  and return behavior, five terminal classes, nested gated choices, and one collapsed technical
  corridor.

The canonical read-only `scripts.rpa` archive was not accessed. Therefore archive before/after
fingerprinting was not applicable. No game or Ren'Py Python was executed, no live story provider
was invoked, and no remote request occurred during acceptance.

## Worker tasks and integration

| Task | Responsibility | Integrated results |
|---|---|---|
| `019f57a5-dd89-7200-82fc-14afbe602dda` | Deterministic route model and durable contracts | `b572575`, `7b44be5`, `5a64946`, `47fd648` |
| `019f57a5-dd89-7200-82fc-14cb9fa622cc` | Parallel scheduler and persistence | `f1e7a93`, `3be6c13` |
| `019f57a5-dd9a-7c42-a842-0aaabd5bd962` | Fixtures and acceptance contracts | `34c0260`, `35c25fa` |
| `019f57c3-35a2-72d3-ae24-6f5e6712f671` | Loopback workflow API | `b810f0a`, `7ddf470`, `a4b4881`, `0a1a986`, `8d1038b` |
| `019f57c3-35a2-72d3-ae24-6f3582f247c9` | Browser Route Map | `7519ec1`, `3d7b287`, `0a4ca72`, `57aeef7` |
| `019f57d4-5c0f-7de1-8e34-61618db14ae8` | Independent adversarial review | `dbcf01d`, final closure `39d32ad` |

Two duplicate setup tasks were stopped and archived before edits; their IDs remain in `TASKS.md`.

Independent review initially found two P1 browser/backend contract mismatches and two P2 dense-map
or lane-identity defects. Each was reproduced, returned to its responsible task, corrected, and
retested. The final review verdict is PASS with no unresolved P0-P2 correctness or security finding.

## Windows verification

Runtime authority: Windows CPython 3.12.

Final independent review at `57aeef7`:

```text
$env:QT_QPA_PLATFORM='offscreen'; python -m pytest -q
exit 0 — 470 passed in 36.15s

python -m pytest <eight focused M07 files> -q
exit 0 — 63 passed in 3.91s

python -m ruff check src tests scripts
exit 0 — All checks passed

python -m mypy --strict src/renpy_story_mapper
exit 0 — no issues in 54 source files

python -m pip check
exit 0 — No broken requirements found

git diff --check
exit 0
```

The final orchestrator closeout rerun after integrating the independent review and completion
documentation also passed all 470 tests in 35.93 seconds; Ruff, strict mypy, `pip check`, and
`git diff --check` again exited 0.

Completion order, adaptive throttling, repair bounds, incremental accounting, cancellation/resume,
durable reopen, zero-call replay, deterministic authority preservation, partial assembly, and
consent/model locks are covered by deterministic mocked-provider tests.

## Chrome verification

The final integrated Chrome harness produced 12 screenshots at 100% and 200% across Route Map,
Detail/Evidence, keyboard, dense paging, organization progress, and partial review states:

- levels: exactly `route_map` and `detail_evidence`;
- initial page: 30 stations and 62 combined items;
- dense first slice: 30 nodes plus 180 edges, 210 items;
- dense second slice: 30 nodes plus 15 edges, 45 items;
- body font: 16 px Segoe UI/system stack;
- exact evidence navigation: passed;
- remote requests: 0;
- provider constructions: 0.

Evidence is stored under `artifacts/m07-browser-acceptance/` and its factual index is
`m07-browser-acceptance.json`.

## Packaging

`python -m pip wheel . --no-deps` completed successfully. The resulting wheel is 323,753 bytes
with SHA-256 `209578598a2b84c034fd16af05c0a092af235cef6c6ffee0847b314399bb8b4b`.

## Limitations and deferred work

- No full MsDenvers or canonical-game cloud rerun was performed. Ten minutes remains an
  optimization target, not a promised completion time.
- The live Luna provider was not invoked in acceptance. Scheduler, safety, cache, usage, and
  partial-result behavior were validated through deterministic provider fixtures.
- Chrome visual acceptance uses packaged production assets with a mock transport. Live
  backend/browser schema alignment is separately exercised through passing ProjectApi and workflow
  integration tests.
- The product remains a private Windows-local application. There is no hosted service, account
  system, telemetry, installer, public release, macOS authority, or LM Studio implementation.
- Generated infographic text can be imperfect; this Markdown report is the factual source of truth.

## Required artifacts

- Goal: `docs/milestones/M07/GOAL.md`
- Task ledger: `docs/milestones/M07/TASKS.md`
- Independent review: `docs/milestones/M07/INDEPENDENT_REVIEW.md`
- Completion report: this file
- Native infographic: `docs/milestones/M07/INFOGRAPHIC.png`
- Pull request: https://github.com/nmpraveen/renpy-story-mapper/pull/11 (unmerged)
