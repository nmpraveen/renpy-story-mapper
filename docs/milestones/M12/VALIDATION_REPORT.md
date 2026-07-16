# M12 validation report

Status: Passed; PR ready

Baseline: `fa8c543f648e085403f7448ab5e89f9b6e6c4fb6`

Changes-requested base: `a02151ebc45d2d05efc6d582a8757fbca87aa6d5`

Validated product head: `40c10fd9bb31e9303efeb302dacd081e1007911c`

Validation date: 2026-07-15

## Changes-requested before/after evidence

| Merge blocker | Before | Corrected evidence |
|---|---|---|
| Supported contradictions | `x` followed by `not x` could survive as two unknown requirements and produce a best-known route | Chronological boolean, literal, and numeric constraint intersection prunes empty states and records exact contradiction fact IDs; unsupported creator expressions remain unknown |
| Completed call frames | Matching call-summary continuation reused the unchanged stack | Successful matching continuation pops the completed frame; 40 sequential calls, nesting, outer returns, shared callees, recursion bounds, and malformed/unresolved returns are covered |
| Full-path state copying | A 600-edge line reached 250,000 accounting units after 408 expansions and stopped incomplete | Parent-linked prefixes complete 500/1,000/2,000 edges using 7,264/14,514/29,014 accounting units and 501/1,001/2,001 prefix records |
| Exact loop acceleration | The helper was unwired; follow-up review also found intermediate-cycle exits could overshoot or falsely conclude state-infeasible | Exact M10-authorized cycles accelerate conservatively. The phase case reaches trust 25 with 13 forward and 12 back edges for both `trust >= 25` and `trust >= 25 and trust < 27` |

No correction changes M10/M11 authority, persistence, cache, cancellation, UI, export, or milestone scope.

## Acceptance matrix

| Criteria | Result | Durable evidence |
|---|---|---|
| AC1-AC4 | Pass | Exact M10/M11 binding, authoritative entries, destination mapping, occurrence selection, provenance, and deterministic request identity in the focused M12 suite |
| AC5-AC11 | Pass | Known/unknown/persistent/scoped state, chronological constraints, exact effects, numeric thresholds, call context, multi-entry scenes, exact loops, and unsafe-loop refusals in 58 solver tests |
| AC12-AC16 | Pass | Deterministic limits, parent prefixes, byte-identical replay, conservative statuses, cancellation, atomic persistence, and 32 persistence/fault/private-harness tests |
| AC17-AC19 | Pass | Real Chrome at 100%/200%, two navigation levels, exact evidence, cancellation/retry, cache replay, deterministic JSON export, and 123 focused tests plus the separate browser run |
| AC20 | Pass | Fast, Focused, Release, scale, browser, private acceptance, input immutability, zero-execution counters, completion artifacts, and independent final review |

## Commands and results

| Command | Result | Artifact or notes |
|---|---|---|
| Focused phase regressions: `pytest tests/test_m12_solver.py -k "intermediate_cycle_exit or intermediate_loop_exit or exact_loop_acceleration" -q` | 3 passed, 55 deselected | Exact intermediate exit and bounded window both reach trust 25 |
| `pytest tests/test_m12_solver.py tests/test_m12_scale_acceptance.py -q` | 64 passed | Final direct corrections and scale gate |
| `scripts/validate.ps1 -Tier Fast` | 39 passed | Ruff passed |
| `scripts/validate.ps1 -Tier Focused -PytestTarget <all 12 test_m12*.py files>` | 123 passed, 1 opt-in browser wrapper skipped | Browser exercised separately |
| `scripts/validate.ps1 -Tier Release` | 788 passed, 6 hardware-sensitive deselected | Ruff, strict mypy over 70 source files, `pip check`, four JavaScript syntax checks, whitespace, isolated sdist/wheel build, install, import, assets, and notices passed |
| `m12_browser_acceptance.py --output-dir output/m12-pr22-cr-browser-phase-final` | Passed | `acceptance.json` SHA-256 `79a74c1ad453f2547ff1090ae45b9383a0ace460243e186ffc107140ea7a35a4`, 6,842 bytes |
| `m12_scale_acceptance.py --output-dir output/m12-pr22-cr-scale-default-phase-final` | Passed | SHA-256 `907704dd48dfe3bf369aeee3d4e0f9b15098ca97660087121f26fce4a4b03bd4`, 7,998 bytes |
| `m12_scale_acceptance.py --profile linear-prefix --linear-edge-counts 500 1000 2000 --output-dir output/m12-pr22-cr-scale-exact-phase-final` | Passed | SHA-256 `cf2ff18394301b29b19ffb613a45ee77ae413ae2cd1756a80716ddb2f039a3db`, 6,050 bytes |
| `pytest tests/test_m12_persistence.py tests/test_m12_fault_acceptance.py tests/test_m12_private_acceptance.py -q` | 32 passed | Atomicity, isolation, cancellation, emergency abort, and private boundaries |
| Emergency-abort targeted test repeated ten times | 10/10 passed | Every wall-clock abort remained uncached and preserved the prior valid cache |
| Exact grind test above repetition limit 16 | 1 passed, 57 deselected | `trust += 1` reaches 25 with one deterministic repeated-action instruction |
| Real private acceptance | Passed | External isolated report SHA-256 `8cd162a76e43d1945ec362117864c86dbb02e4631429a845b629e12d01dd018c`, 5,345 bytes |
| Independent final delivery review on `a02151e..40c10fd` | Pass | 64 focused tests; Ruff; strict mypy; diff check; both phase reproductions exact; no blocking finding |

## Determinism, prefixes, and bounds

- Solver identity remains `m12-static-solver-v1`; limit identity remains `m12-limits-v1`.
- Request/cache identity includes 20,000 expanded states, 10,000 frontier states, 30,000 retained
  states, 40,000 prefix records, call depth 32, repetition per transition 16, three alternatives,
  and 250,000 accounting units.
- The exact linear profile completed 500, 1,000, and 2,000 edges under those normal limits.
  Accounting growth was 1.998073 and 1.999035; serialized-prefix growth was 2.002021 and
  2.017538. All pure-expansion and cache replays were byte-identical.
- Normalized results exclude timestamps, durations, and machine-dependent observations. A
  wall-clock abort creates only an uncached attempt diagnostic and cannot replace a valid result.
- Any deterministic limit, cancellation, or emergency abort remains incomplete and cannot create
  a no-route or state-infeasible conclusion.

## Browser, export, and safety

- Chrome passed at 1440x900/100% and effective 720x450/200% with results visible, no horizontal
  overflow, no browser errors, and no provider, remote, creator-code, Ren'Py, or game execution.
- Cancellation returned a null result, visible Retry, and `Solve cancelled. No result was
  replaced.` at both zoom levels. Exact replay hit cache.
- Detail/Evidence stayed bound to the solved source scene after mutable selection changed. Each
  zoom exposed 11 exact claim/evidence links.
- Deterministic JSON export SHA-256 was
  `17700e37d89b5633e7664fabd0ef07f21d62840e735ccbe720ade2ab9f830607` at both zoom levels.
- Result/evidence screenshot SHA-256 values were 100%
  `1685fa662fdd250b0e8484dd87e63b93cb910a21efcef7550bca214ddb076b90` /
  `b856e8a05d25106cfee025fe2381541d72dd6e1fa3260213d34ee8ecbab9b1cb`, and 200%
  `2739d79f22371d132a0bfe1716cad69fb15c08d44b4d5d539188e6d97616c094` /
  `bcca62338e46e299c283a94c1aa2805532843d3685f648b9722898e8dbeff360`.
- The source fixture remained unchanged at SHA-256
  `16c4cc9c85f41ae703e5bd897369f22d228f6f7a9feca7d76db31a5af8707d64`.

## Private acceptance

- Five stable targets were exercised: three hidden/gated temporary outcomes, one M10 terminal,
  and one persistent lane. The authority catalog exposed all required destination kinds.
- Hidden/gated targets returned honest best-known incomplete routes with exact cache replays. The
  terminal and persistent-lane targets returned `dynamic_or_unknown_possibility`, not an
  unsupported closed-world negative.
- Baseline, target selection, source archive, and adjacent private files remained unchanged. The
  source-archive fingerprint remained SHA-256
  `053abb13454180a2cf9b0aa762e33deda98cf027d9c1e39082f5795982720303`.
- Provider, network, subprocess, creator-code, Ren'Py, and game execution counters were zero. No
  private story text or private input path is tracked.

## Review findings and dispositions

- The single early semantic gate remains `PASS`; the corrections enforce existing AC9-AC14 and do
  not reopen product semantics.
- The changes-requested implementation resolved the four user-reproduced blockers in commits
  `1969b71`, `e081d34`, `88c7259`, and `c247606`, with the exact scale gate in `9eba443`.
- Final delivery review found one phase-soundness defect for exits from an intermediate loop node:
  the first implementation counted full cycles only, causing either a 27-increment route or a false
  state-infeasible result. Commit `40c10fd` adds per-exit phase deltas and deterministic emitted-edge
  ranking. The reviewer reproduced both gates at exactly trust 25 and returned `PASS`.
- No blocking finding remains. The reviewer noted that a prefix transition-count lookup walks its
  parent chain; this is non-critical, does not violate deterministic accounting/serialization
  acceptance, and is deferred outside this merge gate.

## Completion artifact and limitations

- Existing native-generated `INFOGRAPHIC.png` remains valid and unchanged: SHA-256
  `c7e651bec7fa9df2080d06649e4d71c8c205279bf63ea1d5c6b96f845a12f3f5`, 1,437,074 bytes.
- M10 does not prove every scope/default/persistent value. M12 keeps those states unknown or uses an
  explicit entry precondition rather than inventing values.
- Optional thin Markdown output remains omitted; deterministic JSON and browser presentation are
  complete.
- Task controls did not expose verifiable model, reasoning-effort, or fast-mode selectors. This is
  an orchestration limitation, not an M12 product defect; no model-selection code or tests exist.
