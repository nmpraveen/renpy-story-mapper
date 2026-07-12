# M07 Independent Adversarial Review

Review date: 2026-07-12  
Reviewed branch: `codex/m07-two-level-route-map`  
Reviewed tip: `7ddf4702d32b8d60f0a930a9fef0854c5a21c324`  
Merge base with `main`: `e24509c87b95a6584546a3c2ad9cbffaa1cdaf4c`  
Reviewer mode: GPT-5.6 Sol, High reasoning, fast mode disabled  

## Verdict

Not ready to accept. The integrated diff has two unresolved P1 browser/backend contract defects and
two unresolved P2 route rendering/topology defects. No production files were changed. The four
bounded reproductions are strict xfails in `tests/test_m07_independent_review.py`, so they document
current failures and become XPASS failures when production behavior changes.

No live provider was constructed or invoked. The canonical archive was not accessed.

## Integrated diff reviewed

`git diff --stat main...7ddf470` reports 41 files changed, 6,974 insertions, and 1,141 deletions.
The review covered the deterministic route projection and paging, M07 model/workflow, parallel
scheduler and persistence adapter, loopback API/security, packaged browser contracts and UI,
fixtures, browser harness, and M07 tests.

## Findings

### P1 — Integrated Route Map cannot pass the packaged browser response contract

- Backend: `src/renpy_story_mapper/m07_workflow.py:152-182` emits route segments as `lines` and
  exposes total nodes under `totals.nodes`.
- Browser: `src/renpy_story_mapper/web/static/contract.js:29-34` requires `page.edges`; `app.js`
  normalizes and renders `page.edges`.
- Reproduction:
  `py -3.12 -m pytest -q tests/test_m07_independent_review.py::test_integrated_route_payload_satisfies_packaged_browser_contract`
- Result: strict XFAIL because the real API payload has no `edges` or `total_nodes` keys. In a real
  project session, `LocalApi.routeMap()` rejects the response before the Route Map renders.
- Existing Chrome acceptance does not detect this because `mock-api.js` emits `edges`, matching the
  browser but not the backend.

### P1 — Organization prepare/start/status payloads do not match the browser workflow

- Backend status: `src/renpy_story_mapper/m07_workflow.py:355-400` emits `stage`, `scope_counts`,
  `ai_coverage`, `technical_coverage`, token input/output totals, and `assemblies`.
- Browser: `src/renpy_story_mapper/web/static/app.js:193-206` consumes `status`, `scopes`,
  `coverage.ai`, `coverage.technical`, token `used/budget`, and singular `assembly_id`.
- Start response: `src/renpy_story_mapper/web/api.py:327-341` returns the generic
  `{project, analysis}` task envelope, while `app.js:219-230` stores it as organization status and
  polls only when `status === "running"`.
- Prepare also emits `scope` and `budget` in `m07_workflow.py:271-280`, while `app.js:209-222`
  consumes `scopes`, `cached`, and `budgets`.
- Reproduction:
  `py -3.12 -m pytest -q tests/test_m07_independent_review.py::test_integrated_organization_status_satisfies_browser_view_contract`
- Result: strict XFAIL. The real UI cannot accurately show running/cancel/resume/review state even
  though backend consent and scheduler tests pass.

### P2 — Route pagination can exceed the 240-item hard render boundary

- `src/renpy_story_mapper/route_map.py:237-263` and
  `src/renpy_story_mapper/m07_workflow.py:150-156` return all edges incident to the 30 page nodes,
  without an edge/item cap or edge pagination.
- `src/renpy_story_mapper/web/static/contract.js:31-35` rejects more than 180 edges or 240 total
  items.
- Reproduction:
  `py -3.12 -m pytest -q tests/test_m07_independent_review.py::test_route_page_never_exceeds_the_hard_render_cap`
- Result: strict XFAIL with a bounded 30-node/211-edge topology (241 render items). A valid dense
  choice/merge page is rejected instead of remaining navigable.

### P2 — Persistent route edge identity is lost before browser rendering

- Node lanes are persistent and stable, but `src/renpy_story_mapper/route_map.py:618-629` replaces
  every multi-hop semantic role with `corridor` and assigns an unrelated hash-derived `edge_lane`.
- `src/renpy_story_mapper/web/static/graph.js:177` renders persistent colors only for literal edge
  lane IDs `red` or `blue`; real backend lane IDs are hashes. The mock API uses the literals and
  therefore hides the mismatch.
- Reproduction:
  `py -3.12 -m pytest -q tests/test_m07_independent_review.py::test_persistent_route_edges_preserve_their_route_lane_identity`
- Result: strict XFAIL against `tests/fixtures/m06/control_regions.rpy`. Persistent branch edges do
  not share either persistent endpoint lane, and corridor classification obscures detour-versus-
  route semantics.

## Verified behavior

- Deterministic two-level projection, stable ordering/hash behavior, direct Detail/Evidence,
  terminals, loops, unresolved nodes, gates/effects, deterministic assembly, authority preservation,
  cancellation/resume, replay cache, adaptive scheduler behavior, repair bound, and per-attempt
  usage are covered by the focused M07 suite and passed.
- Fresh M07 consent is single-use; prepare/status do not construct a provider; scheduler/provider
  configuration is locked to `gpt-5.6-luna`, High, fast disabled; defaults are 8 initial workers,
  12 maximum workers, and 2 concurrent repairs.
- Loopback origin checks, encoded traversal rejection, and Windows/POSIX path redaction passed the
  added adversarial safety test.
- The post-base picker cancellation guard at `src/renpy_story_mapper/web/static/app.js:68` returns
  before project creation when the save picker supplies no opaque selection ID. The project
  diagnostics correction at `src/renpy_story_mapper/web/api.py:283` now reports schema 6, matching
  `storage.PROJECT_SCHEMA_VERSION`; its loopback regression assertion passes.
- The packaged Chrome mock harness passed 12 captures (six states/exercises at 100% and 200%), with
  exactly two levels, direct evidence navigation markers, keyboard markers, zero remote requests,
  and zero provider constructions. This validates the packaged mock UI, not live API integration.

## Commands and exact results

1. `$env:PYTHONPATH='src'; py -3.12 -m pytest -q tests/test_m07_route_map.py tests/test_m07_model.py tests/test_m07_parallel_organization.py tests/test_m07_parallel_persistence.py tests/test_m07_web_workflow.py tests/test_m07_browser_route_map.py tests/test_m07_acceptance_contracts.py tests/test_m07_independent_review.py`
   — before the render-cap test was added: `56 passed, 3 xfailed in 2.45s`.
2. `$env:PYTHONPATH='src'; py -3.12 -m pytest -q tests/test_m07_independent_review.py`
   — final owned test: `2 passed, 4 xfailed in 0.34s`.
3. `py -3.12 -m ruff check src tests scripts` — `All checks passed!`.
4. `$env:PYTHONPATH='src'; py -3.12 -m mypy --strict src/renpy_story_mapper`
   — `Success: no issues found in 54 source files`.
5. `py -3.12 -m pip check` — `No broken requirements found.`
6. `git diff --check` — exit 0, no output.
7. Chrome harness through `scripts.m07_browser_acceptance.run()` in a Python temporary directory
   — `chrome.exe`, 12 captures, levels `route_map` and `detail_evidence`, 0 remote requests,
   0 provider constructions. Temporary screenshots/report were deleted on context exit.
8. `$env:PYTHONPATH='src'; py -3.12 -m pytest -q` — aborted inside PySide6/pytest-qt at
   `tests/test_m04_contract.py:68` before an assertion result.
9. `$env:PYTHONPATH='src'; $env:QT_QPA_PLATFORM='offscreen'; py -3.12 -m pytest -q`
   — result at `3d7b287`: `463 passed, 4 xfailed in 37.45s`. The isolated legacy GUI test also
   passed offscreen (`1 passed in 0.37s`). Final result at `7ddf470`:
   `463 passed, 4 xfailed in 35.07s`.
10. `$env:PYTHONPATH='src'; py -3.12 -m pytest -q tests/test_m06_5_browser_frontend.py::test_production_picker_shape_and_refresh_lifecycle_are_wired tests/test_m06_5_web_api.py::test_open_view_evidence_and_no_provider_construction tests/test_m07_independent_review.py`
    — `4 passed, 4 xfailed in 1.06s` at `7ddf470`; both post-base compatibility assertions pass.

## Risks and unresolved items

- The four findings above remain unresolved and production behavior was intentionally not fixed.
- The mock Chrome harness is not an end-to-end test of `ProjectApi`; the two P1 schema mismatches
  require an integrated loopback/browser regression test after repair.
- After repair, repeat the full suite with `QT_QPA_PLATFORM=offscreen` (or a stable interactive Qt
  test environment); strict xfails should either pass normally after marker removal or expose any
  incomplete fix.
- No canonical-archive scale or live-provider validation was performed, by scope and safety rule.
