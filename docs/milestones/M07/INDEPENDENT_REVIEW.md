# M07 Independent Adversarial Review — Final Follow-up

Review date: 2026-07-12
Reviewed branch: `codex/m07-two-level-route-map`
Final reviewed tip: `57aeef7ac00da8974f1507734e3812ef9cd462df`
Merge base with `main`: `e24509c87b95a6584546a3c2ad9cbffaa1cdaf4c`
Reviewer mode: GPT-5.6 Sol, High reasoning, fast mode disabled

## Final verdict

Accepted for M07 independent review. The two prior P1 findings and two prior P2 findings are closed.
Their original bounded reproductions now pass as ordinary tests, with no xfail markers. There are no
unresolved P0–P2 correctness or security findings from this review.

The final unfiltered Windows CPython 3.12 suite, Ruff, strict mypy, `pip check`, and
`git diff --check` pass at the exact reviewed tip. No production files were modified by the
reviewer. No live provider was constructed or invoked, and the canonical archive was not accessed.

## Reviewed diff

`git diff --shortstat main...57aeef7` reports 43 files changed, 8,058 insertions, and 1,135
deletions. The review covered deterministic route projection and paging, detour/persistent-route
semantics, the M07 model/workflow, parallel scheduler and persistence, loopback API/security,
consent and provider locks, browser contracts/accessibility, fixtures, and acceptance tests.

## Correction mapping and re-review results

### `a4b4881` — Fix M07 browser API contracts

- Route pages now expose `edges`, `total_nodes`, and bounded item metadata expected by the packaged
  browser.
- Prepare/status/start/cancel/apply responses now expose the browser-consumed organization schema:
  `status`, `scopes`, `coverage`, token usage/budget, and `assembly_id`.
- Re-review tests now pass:
  `test_integrated_route_payload_satisfies_packaged_browser_contract` and
  `test_integrated_organization_status_satisfies_browser_view_contract`.

### `0a1a986` — Keep M07 cancellation polling active

- API task state remains observable while cancellation is in progress, allowing the browser to
  continue polling to a durable terminal state.
- The focused cancellation/resume test passes and still requires a fresh prepared consent run.

### `47fd648` — Bound M07 route pages and preserve lanes

- The authoritative pager enforces 30 nodes, 180 edges, and 240 total render items and supplies a
  deterministic edge continuation cursor.
- Persistent route edges retain the stable persistent lane and no longer collapse multi-hop route
  semantics into an unrelated corridor lane.
- Re-review tests now pass: `test_route_page_never_exceeds_the_hard_render_cap` and
  `test_persistent_route_edges_preserve_their_route_lane_identity`.

### `8d1038b` — Use authoritative M07 route paging

- `M07WorkflowService` now delegates persisted payload paging to the same authoritative bounded
  pager used by the route model, avoiding drift between model and loopback responses.
- High-fanout workflow paging tests pass with stable edge continuation.

### `0a4ca72` — Page dense route map edges

- The browser API, state, mock, UI navigation, and Chrome acceptance harness now carry independent
  node and edge cursors, so dense topology remains navigable without exceeding the render cap.
- Chrome acceptance passes all 12 state/zoom captures at 100% and 200%.

### `57aeef7` — Update browser reset lifecycle assertion

- The stale M06.5 textual assertion now recognizes the authoritative `resetRoutePaging()` lifecycle
  introduced for dense edge pagination.
- This removes the sole out-of-scope full-suite failure observed at `0a4ca72`; the final unfiltered
  suite is green.

## Commands and exact results

1. Initial correction check with strict xfails still present:
   `$env:PYTHONPATH='src'; py -3.12 -m pytest -q tests/test_m07_independent_review.py`
   — `4 failed, 2 passed in 0.32s`; all four failures were `XPASS(strict)`, proving the corrected
   behavior satisfied every reproduction.
2. After removing only the stale xfail markers:
   `$env:PYTHONPATH='src'; py -3.12 -m pytest -q tests/test_m07_independent_review.py`
   — `6 passed in 0.28s`.
3. Focused M07 suite:
   `$env:PYTHONPATH='src'; py -3.12 -m pytest -q tests/test_m07_route_map.py tests/test_m07_model.py tests/test_m07_parallel_organization.py tests/test_m07_parallel_persistence.py tests/test_m07_web_workflow.py tests/test_m07_browser_route_map.py tests/test_m07_acceptance_contracts.py tests/test_m07_independent_review.py`
   — `63 passed in 3.91s`.
4. Correction-specific route/cancellation/reopen tests:
   `$env:PYTHONPATH='src'; py -3.12 -m pytest -q tests/test_m07_route_map.py::test_dense_page_hard_bounds_edge_continuation_and_persisted_authority tests/test_m07_web_workflow.py::test_route_page_stably_caps_high_fanout_edges tests/test_m07_web_workflow.py::test_cancel_preserves_scopes_and_resume_requires_fresh_prepare tests/test_m07_web_workflow.py::test_durable_status_reopens_without_constructing_provider`
   — `4 passed in 1.15s`.
5. Packaged Chrome harness through `scripts.m07_browser_acceptance.run()` in a Python temporary
   directory — `chrome.exe`, 12 captures, levels `route_map` and `detail_evidence`, 0 remote
   requests, 0 provider constructions. Temporary artifacts were deleted on context exit.
6. Final full suite at `57aeef7`:
   `$env:PYTHONPATH='src'; $env:QT_QPA_PLATFORM='offscreen'; py -3.12 -m pytest -q`
   — `470 passed in 36.15s`.
7. `py -3.12 -m ruff check src tests scripts` — `All checks passed!`.
8. `$env:PYTHONPATH='src'; py -3.12 -m mypy --strict src/renpy_story_mapper`
   — `Success: no issues found in 54 source files`.
9. `py -3.12 -m pip check` — `No broken requirements found.`
10. `git diff --check` — exit 0; only Git's LF-to-CRLF working-copy warning was printed.

## Residual risks and scope limits

- The Chrome harness uses the packaged mock transport; live backend/browser schema alignment is
  covered separately by the passing integrated `ProjectApi` review and workflow tests rather than
  one browser process connected to a real project service.
- No live GPT-5.6 Luna call was made. Consent gating, exact model/reasoning/fast-mode locks,
  per-attempt usage, adaptive budgets/timeouts, repair concurrency, cancellation/resume, and
  zero-call replay were validated with deterministic mocked providers.
- No canonical-archive scale run was performed, by explicit scope. Dense synthetic topology covers
  the 30-node/180-edge/240-item pagination boundary and edge continuation adversarially.
