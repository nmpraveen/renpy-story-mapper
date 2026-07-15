# M11 validation report

## Scope and authority

- Branch: `codex/m11-human-scenes`
- Baseline: `cf6da9e076b6141713d4e8f71588fdbcd9ebc911`
- Authority input: M10 `canonical-graph-v1`, exact source generation plus normalized canonical hash
- Durable phase contract: exactly `story_atoms`, `scene_boundaries`, `scene_assembly`, and
  `scene_presentation`
- Pull request: creation explicitly approved; merge remains separately gated

The M11 production modules do not import or call the M01/M02/M06/M07 graph, semantic, state,
control-flow, route-map, or canonical builders. The architecture regression checks this boundary.
M11 retains M10 IDs and provenance and cannot publish or serve a model against a mismatched M10
generation/hash pair.

## Acceptance matrix

| Check | Result |
|---|---|
| Focused M11 pytest plus M10 phase-persistence regression | 49 passed in 8.57 s |
| Full pytest, first final run | 655 passed; one unrelated M06 timing assertion missed at 2.178 s |
| Unrelated M06 isolated reruns | Passed at 1.95 s and 1.84 s |
| Second full pytest | 654 passed; same M06 timing miss plus transient Windows socket exhaustion; both passed in isolation |
| Ruff (`src`, `tests`, M11 scripts) | Passed |
| Strict mypy package and acceptance-script check | Passed, 70 source files |
| `pip check` | Passed |
| Clean detached-worktree package build | Passed; sdist and wheel, 382 inspected entries, zero forbidden artifacts |
| Node syntax (`contract.js`, `api.js`, `app.js`, `graph.js`) | Passed |
| `git diff --check` | Passed |
| Real Chrome M11 acceptance | Passed at 100% and 200% |
| Persisted M11 linear + scene-rich scale | Passed at 500, 1,000, and 2,000 statements |
| Private MsDenvers | Passed direct M11 ground truth, ownership, rejoins, hierarchy, determinism, coverage, provenance, bounds, safety, and immutability |
| Independent release-gate re-review | No remaining P0 or P1 finding |

The full-suite failures were outside M11. The pre-existing 10,000-node M06 control-flow test uses
a strict 2.0-second wall-clock assertion and passed isolated reruns at 1.95 and 1.84 seconds. The
other failure was WinError 10055 after repeated browser/full-suite activity; that server test
passed immediately in isolation. No M11 test failed.

## M10 authority preservation

The accepted M10 baseline and the M11 result retained the same structural authority identifiers:

| M10 authority value | Exact value |
|---|---|
| Canonical payload hash | `769c2931f284fa875a0b8d561d668fcfe21c4d7e0de83c3f09fad71e7d5f6a2f` |
| Source generation | `fea15ae2bc2ce1d8561c54549d8c8b69a7ed355ac93a06c6f077593868f3c77f` |

M11 consumed that payload and did not rebuild or mutate M10 control-flow authority.

## Synthetic contract coverage

The M11 fixture and focused tests cover:

- a short temporary choice with zero arm-local scenes;
- a temporary branch with multiple locations and multiple ordered scenes per arm before rejoin;
- exclusive sibling-arm scene ownership and exclusion of exact merge/post-merge continuation;
- unrelated procedure/module definitions that cannot share a story scene;
- nested temporary containers without lane promotion;
- persistent and terminal route lanes owned only by matching M10 regions, retaining canonical
  parent-lane, split, merge, region, and proof support;
- a narrative callee used once and from multiple story contexts;
- a shared callee used from persistent lanes without false reconvergence;
- a collapsed technical helper and a guarded call with fact provenance;
- explicit day/chapter progression beginning at the next narrative atom;
- weak rejected candidates and hard/strong accepted boundaries with complete provenance;
- repeatable loop scenes, partial order, and return-to-hub relationships;
- overlapping canonical loop regions sharing one human scene;
- minimal split, adjacent merge, orphaned overlay retention, correction republish, and unchanged
  correction reuse;
- failure after a durable phase, last-good retention, and refusal to serve stale/current mixtures;
- map requests that do not load the M10 canonical payload and detail requests that do;
- globally bounded map/detail membership references, callee atoms at occurrence detail, and direct
  lane/chapter/boundary provenance escape.

## Browser evidence

Command:

```powershell
$env:PYTHONPATH='src'
python scripts/m11_browser_acceptance.py --output output/m11-browser-ownership-final
```

Both zoom levels opened M11 as the primary view with two chapter bands, three lanes, 30 of 129
scene elements, and 19 relationships on the first page. The second page remained within 30/180.
Temporary-branch detail exposed three atoms, two arm-local scene groups, five exact evidence
records, 21 canonical escape IDs, and no AI interpretation panel. Canonical escape reached the M10 canonical
view. Layout widths were exactly 1,440/720 CSS pixels with no overflow offenders. Browser errors,
remote requests, and provider constructions were zero.

Artifacts: `output/m11-browser-ownership-final`.

## Linear-scale evidence

Command:

```powershell
$env:PYTHONPATH='src'
python scripts/m11_scale_acceptance.py --output-dir output/m11-scale-ownership-final
```

| Workload / statements | Atoms | Scenes | Coverage | M11 payload | Model bytes | Assembly + validation |
|---|---:|---:|---:|---:|---:|---:|
| Linear / 500 | 502 | 2 | 1,003 | 954,463 | 905,330 | 0.058 s |
| Linear / 1,000 | 1,002 | 2 | 2,003 | 1,900,470 | 1,806,336 | 0.116 s |
| Linear / 2,000 | 2,002 | 2 | 4,003 | 3,792,476 | 3,608,342 | 0.340 s |
| Scene-rich / 500 | 1,002 | 502 | 2,003 | 2,247,555 | 2,050,028 | 0.198 s |
| Scene-rich / 1,000 | 2,002 | 1,002 | 4,003 | 4,489,062 | 4,098,034 | 0.392 s |
| Scene-rich / 2,000 | 4,002 | 2,002 | 8,003 | 8,974,062 | 8,195,034 | 1.096 s |

Both input-doubling intervals are gated. Payload/model growth stayed approximately 2x for both
linear and scene-rich inputs. Assembly-plus-validation growth stayed below the 3.5x timing gate,
including the 1,002-to-2,002-scene interval. Every canonical record retained exact coverage and
the source fixtures were unchanged. The simple whole-corpus design remains adequate, so no finer
incremental architecture was added.

Artifacts: `output/m11-scale-ownership-final`.

## Private MsDenvers evidence

Command:

```powershell
$env:PYTHONPATH='src'
python scripts/m11_private_acceptance.py `
  --baseline <accepted-m10-project.rsmproj> `
  --source <independently-recovered-source.rpy> `
  --archive <private-game-archive> `
  --game-folder <private-game-folder> `
  --output-dir output/m11-private-msdenvers-ownership
```

The harness copied the accepted M10 project and invoked only the M11 publication pipeline; M10 was
not rebuilt. A separate baseline copy supplied the fresh M11 replay. The normal full refresh path
then verified no-write reuse of all four M11 phases.

| Measurement | Result |
|---|---:|
| M10 canonical nodes / M11 atoms | 9,120 / 9,120 |
| Exact canonical coverage entries | 18,683 |
| Scenes / mean atoms per scene | 4,076 / 2.237 |
| Chapters | 1 neutral `Story` chapter |
| Temporary branch containers | 102 |
| Persistent lanes / all lanes | 12 / 13 |
| Call-site occurrences | 5 |
| Cold M11 publication | 6.043 s |
| Separate replay publication | 6.537 s |
| Full unchanged refresh | 2.523 s |
| Durable M11 payload bytes | 21,051,805 |
| Baseline / M11 SQLite bytes | 235,261,952 / 256,344,064 |
| SQLite delta | 21,082,112 |
| Initial map | 30 nodes, 2 relationships, 30/180 limits |

Three of four diagnostic targets were met: cold M11 at most 8 seconds, M11 payloads at most 32
MiB, and final SQLite below 300 MiB. This run's unchanged refresh was 2.523 seconds against the
2-second target. These targets are diagnostic rather than release blockers; unchanged refresh
still reused all four phases and performed no byte write.

The two builds produced identical phase hashes and scene-model hashes. The independently authored
ground-truth manifest rechecked four choices, eight arms, and 33 explicit source lines. The
strengthened acceptance then resolved those anchors against M11 itself: four temporary containers,
eight ordered arm memberships, four exact canonical rejoin chains, 16 representative atom/scene
memberships, and four nested lane-parent relationships. It found zero shared sibling-arm scenes,
escaping/post-rejoin arm scenes, structural-region provenance gaps, lane-anchor mismatches,
nested-lane parent mismatches, or illegal story-procedure cuts. Exact coverage and provenance
connect those accepted M10 anchors to M11 without source-text duplication.
The accepted M10 project, recovered source, and scripts archive retained their original size, hash,
and modification time. No provider was constructed, no remote request occurred, and no game or
creator Python executed.

Artifacts: `output/m11-private-msdenvers-ownership`.

## Scene-quality review evidence

The review-only private diagnostic found 4,076 scenes and the following atom-count distribution:

| Measure | Result |
|---|---:|
| Singleton scenes | 337 (8.268%) |
| Median atoms | 2.0 |
| p75 / p90 / p99 | 2 / 3 / 5 |
| Maximum atoms | 17 |

Accepted boundaries grouped by strength were 3,784 hard, 7 strong, 0 weak, and 0 conflict. The
six deterministic rule/reason groups were `canonical_module_boundary` (28),
`canonical_procedure_entry` (145), `corpus_start` (1), `explicit_scene_reset` (3,598),
`persistent_lane_entry` (12), and `visual_context_change` (7).

The committed [scene-quality evidence](review-evidence/SCENE_QUALITY_EVIDENCE.md) contains 18
privacy-safe representative records around all four known Day 1 choices, arm entries, long-arm
tails, and exact rejoins. It also links synthetic 100% and 200% browser captures showing the
common spine, a temporary multi-scene branch, a persistent/terminal lane split, scene detail, and
the direct provenance escape to M10. The diagnostic found no severe segmentation error. It did
not change or retune the production segmentation algorithm.

## Performance correction evidence

The first diagnostic run took 35.517 seconds because persistence repeatedly normalized and hashed
the same 161 MB canonical mapping and reloaded prior large phase envelopes. Profiling separated the
actual deterministic phases from persistence overhead. The final implementation:

- reuses an exact canonical hash already computed by M10;
- caches that binding only for the lifetime and identity of one in-memory payload;
- validates prior phase pointers incrementally and validates all four result envelopes once inside
  the atomic publish transaction;
- computes the scene-model hash from the already normalized assembly mapping once.

The exact integrity checks did not change. Final cold private publication remained 6.043 seconds
after arm-local ownership, procedure boundaries, and stronger private checks were added, and all
persistence/corruption/failure tests still pass.

## Durable failure and correction behavior

- Every phase result is content addressed by its input hash and paired with source generation,
  canonical schema, and canonical hash.
- Checkpoint and working-pointer updates share one transaction.
- Publish validates all four envelopes inside its transaction before moving the published pointer.
- A failed newer build leaves the old published pointer and durable new partials intact.
- Current selection refuses an old publication after the current M10 pair changes.
- Correction overlays are exact-bound. Split changes one target boundary to hard/accepted; merge
  changes one adjacent boundary to weak/rejected. Other corrections remain durable but inactive.
- Correction publication reuses atom/boundary phases, replaces assembly/presentation, and avoids
  writes on identical reapplication.

## Non-goals and limitations

M11 deliberately excludes:

- AI narrative summaries or titles;
- character motives or full-plot summaries;
- route-to-target and path-requirement solving;
- runtime tracing and dynamic framework adapters;
- global AI stitching;
- source-window, halo, scope scheduler, dirty-neighbor, and cross-generation reuse systems;
- arbitrary scene editing or a second control-flow authority.

M11 is a deterministic scene draft. Weak boundaries remain rejected candidates and are not claimed
as objective. The private corpus has no reliable source-authored day/chapter marker in its accepted
canonical input, so the neutral `Story` chapter is correct. It also has no M10 loop region, so it
does not fabricate repeatable hubs. Synthetic loop behavior is covered separately.

No unresolved P0 or P1 M11 finding is known. Pull-request creation is approved; merge and M12
remain separately gated.
