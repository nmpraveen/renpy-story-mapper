# M10 validation report

## Result

M10 passes the approved deterministic whole-project graph acceptance criteria on branch
`codex/m10-canonical-graph`. The verified base is M09 commit
`f327896a1f55784e89982cdf8886722255e9b0df`; the validated implementation head before this
report is `c286ef5fb67d50df1a2f8c8b28e494ec0a7715ea`.

No pull request was created. No provider or other AI call was made by the M10 workflow or
private acceptance run.

## Delivered commits

1. `7d62f41` — Define M10 canonical graph contract
2. `bccec38` — Persist the canonical whole-project graph
3. `ebd3fcc` — Preserve generation-bound analysis phases
4. `cdc6099` — Add deterministic M10 inspection projection
5. `7ecdc0c` — Expose bounded M10 graph inspection
6. `c286ef5` — Validate M10 against private Day 1 facts

Relative to M09, these commits change 30 files with 3,782 insertions and 128 deletions.

## Acceptance summary

| Criterion | Result |
|---|---|
| Relevant M09 behavior | Full repository suite passes: 572 tests |
| Ruff / strict mypy | Pass; mypy checked 61 source files |
| Package health | `pip check` passes; isolated wheel build passes |
| Headless deterministic core | Pass with PySide6 imports blocked |
| `.rpy`, supported `.rpyc`, `.rpa` ingestion | 33 focused ingestion/headless tests pass |
| Game-code safety | Parser/recovery remains inert; private run executed no game/creator Python |
| Canonical project graph | Versioned `m10_canonical_graph` is persisted with evidence/proofs |
| Conditions and effects | Preserved as canonical facts with origin references |
| Regions and reachability | Choices, conditions, loops, merges, terminals, and unresolved behavior classified conservatively |
| Generation integrity | Every phase is generation-bound; stale/partial/failed states and last-good retention tested |
| Simplified inspection | Separate projection; suppressions retain canonical escape IDs |
| Browser inspection | 30-node / 180-edge hard limits, paging, fixed layout, filters, search, focus, evidence, canonical escape |
| Structural determinism | Normalized canonical and simplified bytes match on unchanged replay |
| No path explosion | Compact graph retained; playthrough combinations are not enumerated |
| No M10 AI/global stitch | M10 imports no provider, scene-packet, scene-projection, or stitch path |
| Private Day 1 regression | Passes independent source-authored manifest |
| Synthetic parity | Generic fixture covers ordered choices, conditions, effects, loops, rejoins, terminals, and unresolved transfers |

## Commands and timings

| Command | Result | Timing |
|---|---:|---:|
| `.venv\Scripts\python.exe -m pytest -q` | 572 passed | 57.01 s pytest / 57.384 s wall |
| `.venv\Scripts\python.exe -m ruff check src tests scripts` | Pass | included in 0.924 s quality run |
| `.venv\Scripts\python.exe -m mypy src/renpy_story_mapper` | Pass, 61 files | included in 0.924 s quality run |
| `.venv\Scripts\python.exe -m pip check` | No broken requirements | included in 0.924 s quality run |
| `.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir output/package-check` | Wheel built, SHA-256 `79ad8fe00672ddc1316fd1b130a8efd43a9c0d1ecf9b7e0837b408c87099afac` | 4.055 s |
| `.venv\Scripts\python.exe -m pytest -q tests/test_m06_ingestion.py tests/test_rpa.py tests/test_m10_headless_core.py` | 33 passed | 3.19 s pytest / 3.547 s wall |
| `.venv\Scripts\python.exe scripts/m10_private_acceptance.py --output-dir output/m10-private-msdenvers` | Pass | 2.914 s |
| `.venv\Scripts\python.exe scripts/m07_browser_acceptance.py --output output/playwright/m07-regression` | Pass at 100% and 200%; 0 remote requests; 0 provider constructions | 3.8 s wall |
| Playwright CLI live inspection | Inspection, exact outcome detail/evidence, canonical focus, fixed continuation layout pass | manual bounded run |
| `node --check` on packaged JavaScript | Pass | included in browser slice validation |
| `git diff --check` | Pass | final check |

`python -m build --version` was unavailable because the optional `build` frontend is not
installed. Pip's isolated PEP 517 wheel build was used instead and passed.

## Private MsDenvers Day 1 result

The ground-truth manifest at `tests/private/m10_msdenvers_day1_ground_truth.json` was manually
transcribed from recovered source SHA-256
`6dfe1bd2a6f05bc07c024ab29e3a64a465679eb0597c6a1c9ddb1b32806e21e8`. It records exact
choice captions, source lines, ordered arms, branch targets, rejoins, conditions, effects, and
an opaque visibility case. The manifest verification reads source text directly; it does not use
production analyzer output.

The separate analyzer comparison produced:

- 4 Day 1 choices and 8 ordered outcomes;
- 4 source-known rejoins represented by canonical regions and reachable projected merges;
- 5 relevant conditions and 9 state effects preserved;
- 1 opaque source visibility case retained;
- 1,441 canonical nodes / 1,467 canonical edges;
- 70 simplified nodes / 96 simplified edges;
- identical canonical and projection structural bytes on a second unchanged analysis;
- 0 provider calls and 0 production game-name hardcodes;
- unchanged recovered-source and archive fingerprints.

The private check exposed one real M06 defect: branch arm ordinals were sorted by hashed edge ID.
M06 now uses parser-authored `choice_index` / `branch_index`, with stable ID only as a fallback.
A generic three-arm test covers the correction.

## Intentional behavior changes and deviations

- Failed initial analysis now retains a valid partial project when generation state exists.
- Later phase failures retain the last-good canonical graph and simplified projection with explicit
  stale generation labels.
- M06 arm ordinals now preserve source order rather than hash order.
- The optional `build` module was absent; an isolated pip wheel build was the package-build check.

There were no scope deviations. M10 did not add scene packets, scene grouping, provider work,
global stitching, route solving, or game-specific production logic.

## Known limitations and deferred work

- Arbitrary creator Python and dynamic transfers remain unresolved; M10 shows them rather than
  guessing feasibility.
- Reachability is deliberately conservative. `possibly_dead` and
  `unreachable_in_resolved_static_graph` are not claims of proven impossibility.
- The simplified map is a structural inspection view, not a human-authored scene/chapter map.
- Dense canonical graphs require deterministic pagination and continuation portals.
- Alias and support-terminal suppression are presentation decisions only; consumers needing full
  fidelity must use canonical escape IDs.
- Consumers must honor `m10_analysis_state` generation/freshness fields and must not combine stale
  and current phases.
- Route-to-target solving, human scene boundaries, semantic summaries, dynamic framework support,
  and optional runtime trace validation remain later milestones.

## Review gate

Implementation and validation are complete. Stop here and wait for explicit approval before
creating a pull request.
