# M11 validation report

## Scope and authority

- Branch: `codex/m11-human-scenes`
- Pull request: #20, awaiting final review
- Baseline: `cf6da9e076b6141713d4e8f71588fdbcd9ebc911`
- Authority input: M10 `canonical-graph-v1`, exact source generation and normalized canonical hash
- Durable phases: `story_atoms`, `scene_boundaries`, `scene_assembly`, `scene_presentation`

This was the bounded correction pass for browser node ordering, M10 story chronology/scene-flow
projection, and human boundary semantics. The existing five commits and architecture were
retained. Production M11 still does not import or call the M01/M02/M06/M07 graph, semantic, state,
control-flow, route-map, or canonical builders.

## Authority and safety invariants

| Invariant | Result |
|---|---|
| M10 canonical payload hash | `769c2931f284fa875a0b8d561d668fcfe21c4d7e0de83c3f09fad71e7d5f6a2f` unchanged |
| M10 source generation | `fea15ae2bc2ce1d8561c54549d8c8b69a7ed355ac93a06c6f077593868f3c77f` unchanged |
| Private baseline/source/archive fingerprints | Unchanged |
| Provider constructions | 0 |
| Remote/network requests | 0 |
| Game or creator Python executions | 0 |
| Commercial game source/assets committed | 0 |

M11 uses exact M10 canonical-edge precedence inside each lane and temporary arm. Existing route
order and source location are deterministic fallback/tie-break inputs. Scene-flow relationships
are bounded, deduplicated projections of resolved canonical edges crossing assembled scenes; they
are not invented edges and do not repeat control-flow analysis.

## Acceptance matrix

| Check | Result |
|---|---|
| Focused M11 pytest plus M10 phase persistence | 54 passed in 10.78 s |
| Full Windows pytest | 660 passed; one unrelated M06 timing assertion at 2.075 s versus 2.0 s |
| Unrelated M06 isolated rerun | Passed at 1.85 s |
| Ruff (`src`, `tests`, M11 scripts) | Passed |
| Strict mypy package and acceptance scripts | Passed, 70 source files |
| `pip check` | Passed |
| Package build/inspection | Passed isolated wheel build; 91 entries, no forbidden artifacts |
| Node syntax (`contract.js`, `api.js`, `app.js`, `graph.js`) | Passed |
| `git diff --check` | Passed |
| Real Chrome M11 acceptance | Passed at 100% and 200% |
| Persisted M11 linear + scene-rich scale | Passed at 500, 1,000, and 2,000 statements |
| Private MsDenvers | Passed chronology, ownership, rejoins, hierarchy, determinism, coverage, provenance, bounds, safety, and immutability |

The full-suite miss is outside M11. The pre-existing M06 10,000-node/14,998-edge test uses a
strict 2.0-second wall-clock assertion; it measured 2.075 seconds in the loaded full suite and 1.85
seconds immediately in isolation. Earlier PR validation also observed the same timing variance and
a transient WinError 10055 socket-exhaustion failure after repeated browser/full-suite activity;
both unrelated tests passed in isolation. No M11 test failed.

## Synthetic regression coverage

The focused suite directly covers:

- physically out-of-order label definitions displayed in resolved story order
  `start -> later -> ending`;
- ordinary cross-scene common-spine connections projected from exact M10 edges;
- at least ten same-lane browser nodes with numeric `page_order -> order`, one card per loaded node,
  distinct positions, and no identical same-lane x/y pair;
- one human scene spanning two labels with resolved normal continuation;
- multiple `scene`/`show`/`hide` operations inside one conversation, with rejected weak decisions
  and provenance retained;
- reinforced location/transfer/minimum-run scene-reset decisions;
- unrelated procedures remaining separated;
- persistent route entries and exact merges retaining hard ownership;
- temporary arm scenes and exact rejoins retaining exclusive ownership;
- branch, call, loop, persistent-lane, and rejoin topology without flattening;
- narrative call occurrences, shared callees without false merges, guarded calls, repeatable loops,
  nested temporary containers, and nested persistent lanes;
- minimal split/merge overlays, durable phase failure/reuse, stale/current refusal, and bounded map/
  detail provenance escape.

## Browser evidence

Command:

```powershell
$env:PYTHONPATH='src'
python scripts/m11_browser_acceptance.py --output output/m11-pr20-corrections-browser-final8
```

Real Chrome opened M11 as the primary view at both zoom levels. Each run loaded 30 nodes and 37
relationships. All 30 loaded node IDs had rendered cards and graph positions. The page contained
14 same-lane scene nodes and all 14 positions were distinct; there were no identical x/y
coordinates in any lane. Numeric `page_order` mapping passed. Eight persistent-lane cards were
present. Temporary-branch detail exposed 13 atoms, arm-local scene counts of three and one, 14
evidence records, 44 canonical escape IDs, and no AI panel. Provider constructions, remote requests,
browser errors, and overflow offenders were zero.

Committed captures:

- [100% common-spine overview](review-evidence/screenshots/m11-scenes-100.png)
- [100% persistent split cards](review-evidence/screenshots/m11-scenes-cards-100.png)
- [100% scene detail](review-evidence/screenshots/m11-scene-detail-100.png)
- [100% M10 provenance escape](review-evidence/screenshots/m11-canonical-escape-100.png)
- [200% common-spine overview](review-evidence/screenshots/m11-scenes-200.png)
- [200% persistent split cards](review-evidence/screenshots/m11-scenes-cards-200.png)
- [200% scene detail](review-evidence/screenshots/m11-scene-detail-200.png)
- [200% M10 provenance escape](review-evidence/screenshots/m11-canonical-escape-200.png)

Hashes and capture descriptions are in the [screenshot manifest](review-evidence/screenshots/README.md).

## Linear and scene-rich scale evidence

Command:

```powershell
$env:PYTHONPATH='src'
python scripts/m11_scale_acceptance.py --output-dir output/m11-pr20-corrections-scale-final
```

| Workload / statements | Atoms | Scenes | Accepted / rejected candidates | M11 payload | Model bytes | Assembly + validation |
|---|---:|---:|---:|---:|---:|---:|
| Linear / 500 | 502 | 2 | 0 / 0 | 954,684 | 905,330 | 0.060 s |
| Linear / 1,000 | 1,002 | 2 | 0 / 0 | 1,900,691 | 1,806,336 | 0.118 s |
| Linear / 2,000 | 2,002 | 2 | 0 / 0 | 3,792,691 | 3,608,336 | 0.267 s |
| Scene-rich / 500 | 1,002 | 168 | 166 / 334 | 2,084,200 | 1,918,653 | 0.130 s |
| Scene-rich / 1,000 | 2,002 | 335 | 333 / 667 | 4,162,825 | 3,835,634 | 0.274 s |
| Scene-rich / 2,000 | 4,002 | 668 | 666 / 1,334 | 8,318,871 | 7,668,490 | 0.596 s |

Payload/model growth remained approximately 2x on both doubling intervals. Assembly growth stayed
at or below 2.273x. Every canonical record retained exact coverage, input fixtures were unchanged,
and scene-rich inputs produced both accepted reinforced resets and retained rejected visual
candidates. There is no universal target for the number of scenes.

## Private MsDenvers evidence

The private harness copied the accepted M10 project and invoked only M11 publication; it did not
rebuild M10. A separate copy supplied the replay, and the normal refresh path verified no-write
reuse of all four phases.

| Measurement | Result |
|---|---:|
| M10 canonical nodes / M11 atoms | 9,120 / 9,120 |
| Exact canonical coverage entries | 18,683 |
| Scenes / mean atoms per scene | 1,812 / 5.033 |
| Chapters | 1 neutral `Story` chapter |
| Temporary containers | 102 |
| Persistent lanes / all lanes | 12 / 13 |
| Call-site occurrences / loop regions | 5 / 0 |
| Cold / replay publication | 5.201 / 5.305 s |
| Full unchanged refresh | 1.635 s |
| Durable M11 payload bytes | 19,988,898 |
| Baseline / M11 SQLite bytes | 235,261,952 / 255,279,104 |
| SQLite delta | 20,017,152 |
| Initial map | 30 nodes, 34 relationships, 30/180 limits |

All four diagnostic targets passed: cold publication at most eight seconds, unchanged refresh at
most two seconds, payloads at most 32 MiB, and final SQLite below 300 MiB. The unchanged refresh
reused all four phases without a byte write.

Replay produced identical phase and scene-model hashes. Direct M11 ground truth resolved four
choices, eight ordered arms, four exact canonical rejoin chains, 16 representative atom/scene
memberships, and four nested lane-parent relationships. It found zero shared sibling-arm scenes,
escaping/post-rejoin arm scenes, region-provenance gaps, lane-anchor/parent mismatches, or illegal
story-procedure joins. The accepted project, recovered source, and archive retained their original
size, hash, and modification time. No private source, project, archive, or asset is tracked.

## Before/after boundary and scene evidence

| Scene distribution | Before correction | After correction |
|---|---:|---:|
| Scenes | 4,076 | 1,812 |
| Singleton scenes | 337 (8.268%) | 276 (15.232%) |
| Median atoms | 2 | 6 |
| p75 / p90 / p99 | 2 / 3 / 5 | 6 / 7 / 10 |
| Maximum atoms | 17 | 25 |

Accepted boundaries changed from 3,784 hard + 7 strong to 292 hard + 1,335 strong; accepted weak
and conflict counts remained zero. Before-correction accepted rules were:

| Rule | Strength | Count |
|---|---|---:|
| `canonical_module_boundary` | hard | 28 |
| `canonical_procedure_entry` | hard | 145 |
| `corpus_start` | hard | 1 |
| `explicit_scene_reset` | hard | 3,598 |
| `persistent_lane_entry` | hard | 12 |
| `visual_context_change` | strong | 7 |

After-correction accepted rules were:

| Rule | Strength | Count |
|---|---|---:|
| `canonical_module_boundary` | hard | 28 |
| `canonical_procedure_entry` | hard | 86 |
| `corpus_start` | hard | 1 |
| `persistent_lane_entry` | hard | 12 |
| `terminal_transition` | hard | 34 |
| `unresolved_safety` | hard | 131 |
| `minimum_narrative_run` | strong | 1,328 |
| `reinforced_resolved_transfer` | strong | 7 |

The full [scene-quality evidence](review-evidence/SCENE_QUALITY_EVIDENCE.md) also reports rejected
candidate rule/reason groups and contains 19 privacy-safe ordered scene sequences around the four
known Day 1 choices, arm progressions, and exact rejoins. The records include scene ID, lane,
chapter, atom count, first/last privacy-safe locator, accepted boundary reason, temporary-container
membership, and a bounded generic source description. They contain no commercial dialogue or
source text. The evidence validates chronology, readability, provenance, and structural ownership;
it is not a universal scene-count target.

## Durable failure and correction behavior

- Every phase is content addressed by exact input hash and paired with source generation,
  canonical schema, and canonical hash.
- Checkpoint and working-pointer updates share one transaction; publish validates all phase
  envelopes before moving the published pointer.
- A failed newer build leaves the prior publication and new durable partials intact; current
  selection refuses a publication when the M10 authority pair changes.
- Split changes one target boundary to hard/accepted. Merge changes one adjacent boundary to
  weak/rejected. Other overlays remain durable but inactive.
- Identical correction reapplication performs no writes.

## Non-goals and limitations

M11 excludes AI narrative summaries/titles, character motives, full-plot summaries, route-to-target
or path-requirement solving, runtime tracing, dynamic framework adapters, global AI stitching,
arbitrary scene editing, and any second control-flow authority. It does not add source-window,
halo, dirty-neighbor, or cross-generation scope-reuse systems because measured whole-corpus
processing remains adequate.

Weak boundaries are retained candidates, not objective truth. The private corpus has no reliable
source-authored day/chapter marker in its accepted canonical input, so the neutral `Story` chapter
is correct. It has no M10 loop region, so M11 fabricates none; loop behavior is covered
synthetically. Scene counts are evidence-driven and have no universal target.

The three requested P1 corrections are complete. PR #20 is awaiting final review, is not merged,
and M12 has not begun.
