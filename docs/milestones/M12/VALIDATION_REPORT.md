# M12 validation report

Status: Passed

Baseline: `fa8c543f648e085403f7448ab5e89f9b6e6c4fb6`

Validated product head: `1df83098872fb63d434ff3e59a79e0f286944260`

Validation date: 2026-07-15

## Acceptance matrix

| Criteria | Result | Commands / durable evidence |
|---|---|---|
| AC1-AC4 | Pass | Focused authority/model/service/solver tests prove exact M10/M11 binding, authoritative entry, all destination kinds, occurrence selection, and deterministic identity |
| AC5-AC11 | Pass | Solver fixtures cover known/unknown/persistent/scoped state, chronology, distinct entry assumptions, proven and repeated effects, numeric thresholds, call context, multi-entry scenes, and unsafe loops |
| AC12-AC16 | Pass | Byte-identical scale reports, deterministic budget termination, alternatives, conservative statuses, 32 persistence/fault/private-harness tests, and 10 consecutive emergency-abort replays |
| AC17-AC19 | Pass | Real Chrome at 100% and 200%, two navigation levels, visible results/evidence, cancellation/retry, exact cache replay, deterministic JSON export, and 97 focused M12 tests |
| AC20 | Pass | Fast/Focused/Release, private acceptance and fingerprints, zero execution/remote activity, native infographic, and two independent final review passes |

## Validation commands

| Command | Exit code / result | Artifact or notes |
|---|---|---|
| `powershell -ExecutionPolicy Bypass -File scripts/validate.ps1 -Tier Fast` | 0; 39 passed | Ruff passed |
| `scripts/validate.ps1 -Tier Focused -PytestTarget <all 12 test_m12*.py files>` | 0; 97 passed, 1 opt-in browser test skipped | Browser exercised separately |
| `powershell -ExecutionPolicy Bypass -File scripts/validate.ps1 -Tier Release` | 0; 762 passed, 6 hardware-sensitive deselected | Ruff; strict mypy over 70 source files; `pip check`; four JavaScript syntax checks; whitespace; isolated sdist/wheel build, install, import, assets, and notice all passed |
| `py -3.12 scripts/m12_browser_acceptance.py --output-dir output/m12-pr-ready-1df8309-browser` with `PYTHONPATH=src` | 0; passed | `acceptance.json` SHA-256 `0256aeefd8b34df69c3da7b1fcc91009c01b98b7ce516e6847dfea80a58c4207` |
| Two `m12_scale_acceptance.py` runs in `output/m12-pr-ready-1df8309-scale-run{1,2}` | 0; both passed | Reports byte-identical; SHA-256 `97f5194e6a2264d8006126f87088c13bb6dd3891cf217d8c76f5a2b0f1f2fcbc` |
| `py -3.12 -m pytest tests/test_m12_persistence.py tests/test_m12_fault_acceptance.py tests/test_m12_private_acceptance.py -q` | 0; 32 passed | Atomic cache, stale/failure isolation, cancellation, emergency abort, and private boundaries |
| Real private acceptance through `scripts/m12_private_acceptance.py` | 0; passed | External isolated report SHA-256 `194551a06be474bfaec41f6e5f01a75c6d0240b02cfa6d28c296dc50791d892e`; private machine path deliberately not tracked |
| Emergency-abort targeted replay repeated 10 times | 0; 10/10 passed | Ultra-small wall-clock deadline remained uncached and preserved prior valid cache |
| Final semantic/contract review | Pass | Exact range baseline through `1df83098872fb63d434ff3e59a79e0f286944260`; targeted 11 passed, full M12 97 passed/1 skipped, Ruff/mypy/JS/manifest/diff passed |
| Final delivery/correctness review | Pass | Exact same range; targeted 8 passed, package/manifest 15 passed, repeated A-B-A scene probe passed, Ruff/mypy/JS/diff passed |

## Determinism and bounds

- Solver identity is `m12-static-solver-v1`; deterministic limit identity is
  `m12-limits-v1`.
- Every request/cache identity records the v1 limits: 20,000 expanded states; 10,000 frontier
  states; 30,000 retained states; 40,000 prefix records; call depth 32; repetition per
  transition 16; three alternatives; and 250,000 accounting units.
- Linear scale runs expanded 101, 197, and 389 states for 24, 48, and 96 statements.
  Expansion-growth ratios were 1.950495 and 1.974619, below the 3.0 gate.
- The complex workload solved only selected targets. Its alternative and threshold-loop cases
  terminated as incomplete under deterministic limits; neither produced a negative conclusion.
- Pure expansion and cache replays were identical. Normalized route bytes exclude durations,
  timestamps, and machine-dependent observations; emergency durations exist only in uncached
  attempt diagnostics.

## Browser, export, and safety evidence

- Chrome passed at 1440x900/100% and effective 720x450/200% with results in view, no horizontal
  overflow, no browser errors, and no provider construction, remote request, or creator/game
  execution.
- Cancellation returned `cancelled`, retained a null result, exposed Retry, and reported
  `Solve cancelled. No result was replaced.` at both zoom levels.
- Exact replay hit cache. Detail/Evidence opened the solved-source scene even after the mutable
  source selection changed. Each zoom exposed 11 exact claim-evidence links.
- Deterministic JSON export SHA-256 was
  `c5eb5bf13b62948c2ae2a952a6ebecc649da06ea1d503cb9e5bc7e522498ae4b`
  at both zoom levels.
- Screenshot SHA-256 values: result 100%
  `9585b078d694fbb4b4e1aeef82826fe60f2ecb2e91d11e230b0039831dcf83e6`;
  evidence 100% `b856e8a05d25106cfee025fe2381541d72dd6e1fa3260213d34ee8ecbab9b1cb`;
  result 200% `2739d79f22371d132a0bfe1716cad69fb15c08d44b4d5d539188e6d97616c094`;
  evidence 200% `bcca62338e46e299c283a94c1aa2805532843d3685f648b9722898e8dbeff360`.
- The source fixture SHA-256 remained
  `16c4cc9c85f41ae703e5bd897369f22d228f6f7a9feca7d76db31a5af8707d64`.

## Private acceptance

- Five stable authority targets were selected: three hidden/gated temporary outcomes, one M10
  terminal, and one persistent lane. The catalog exposed generic scene, exact occurrence,
  temporary outcome, persistent lane, and terminal destination kinds.
- The three gated targets returned honest best-known/incomplete routes with ordered scene counts
  7, 36, and 28. The terminal and persistent lane returned `No proven route` with technical
  status `dynamic_or_unknown_possibility`, not a closed-world negative.
- All exact replays hit cache and produced equal normalized bytes.
- Accepted baseline, target selection, archive, and adjacent private files remained unchanged.
  The archive fingerprint remained SHA-256
  `053abb13454180a2cf9b0aa762e33deda98cf027d9c1e39082f5795982720303`,
  size 2,140,282 bytes, last-write time `2026-07-03T01:11:16+00:00`.
- Provider, network, subprocess, creator-code, Ren'Py, and game execution counters were all zero.
  No private path or private story text is tracked.

## Review findings and dispositions

- The single early semantic gate recorded `PASS` before broad implementation.
- Final review found a UI cancellation publication race. Commit `ea52f92` invalidates the solve
  token before the first cancellation await; real-browser cancellation now publishes no result.
- Final semantic review found chronology loss when an entry-supported gate was revisited after a
  possible write. Commit `5faa12a` preserves exact chronological attributions and state identity.
- Adversarial follow-up found one entry assumption could be counted more than once as supporting
  effects accumulated. Commit `1df8309` ranks distinct entry assumptions once, renders one start
  instruction, deduplicates identical effect claims, and preserves ordered scene/choice/repeat
  instructions. The independent three-edge-versus-four-edge probe passes.
- The first post-cancellation Release attempt exposed a stale `app.js` integrity hash. Commit
  `69c1928` refreshed the canonical LF manifest entry; the final Release tier passed completely.
- Both independent final reviews returned `PASS` on exact product head
  `1df83098872fb63d434ff3e59a79e0f286944260`. No blocking finding remains.

## Completion artifact

- `INFOGRAPHIC.png` was generated with native image generation and visually reviewed.
- SHA-256:
  `c7e651bec7fa9df2080d06649e4d71c8c205279bf63ea1d5c6b96f845a12f3f5`;
  size 1,437,074 bytes.

## Limitations and permitted dispositions

- M10 does not prove complete scope/default/persistent initialization for every variable. M12
  preserves unknown state and treats persistent values as external preconditions unless a
  selected path proves them.
- Private terminal/lane targets remain dynamic/unknown because available static authority does
  not support a closed-world negative. This is required conservative behavior.
- Deterministic JSON export is delivered. Optional thin Markdown formatting was omitted because
  it would duplicate the deterministic presentation and was not allowed to delay correctness.
- No M12 migration was needed: existing atomic, checksummed payload transactions support isolated,
  exact, versioned M12 result and attempt records.
- Worker controls did not expose or verify model, reasoning-effort, or fast-mode selectors. This
  orchestration limitation created no product code or test.
