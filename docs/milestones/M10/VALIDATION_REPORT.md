# M10 post-merge hardening validation report

## Report status

This is the correction-branch validation report for M10 after its merge to `main`.

- Baseline `main`: `68923e494d3c8200514845191ced683239e714fc`
- Correction branch: `codex/m10-post-merge-hardening`
- Corrective pull request: not created; explicit approval is still required
- Final validation state: **complete; ready for review, but not approved for PR creation**

The merged M10 source remains the baseline. This branch does not revert M10, reset to M09,
rewrite history, or begin M11, M12, or M13.

## Baseline and review protocol

The latest `main` was fetched and the correction branch was created from exact commit
`68923e494d3c8200514845191ced683239e714fc`. The supplied merged-source ZIP was compared with the
baseline by tracked Git blob and had no missing, extra, or differing tracked files.
It contained the same 253 tracked files and had SHA-256
`1210A1EF193D2BDEFD23F6C1A897AA605D98B0A342A884BDAB15A61AA3A4501A`.

The focused M10 baseline passed before correction, but targeted regression tests then reproduced
the reported blocking behavior. The regression-first commit was kept separate from the fixes.

## Commit history

1. `ea55c82` - reproduce the post-merge blockers with failing regression tests
2. `c9e4812` - derive reachability from resolved M06 control flow and add deterministic proofs
3. `41b9d91` - enforce coherent generation read models and canonical-without-projection access
4. `d10ca96` - expose retained results after failures and make M10 inspection the default
5. `ebc0293` - add whole-graph focus and derivation detail
6. `92b67dc` - strengthen deterministic acceptance, nested-arm attachment, and phase timing
7. `docs(m10): record corrected validation` - this report's documentation-only commit; its exact
   hash is supplied in the final handoff because a commit cannot contain its own hash

The regression-first history must not be squashed away before review.

## Defect dispositions

| Review finding | Disposition in the correction branch | Validation status |
|---|---|---|
| 1. Synthetic M06 reachability | Reachability now traverses resolved M06 edges from the actual entry procedure/label and includes procedure exits and return sites. M01 is supporting evidence only. `resolved_static_reachability` records the derivation. | Passed targeted and full-suite regressions |
| 2. Cross-generation canonical/projection composition | API selection validates payload and analysis-state schema, source generation, and canonical hash. A newer canonical payload cannot resolve an older simplified payload. | Passed caption-change, tampered-state, and generation-mismatch regressions |
| 3. Canonical unavailable without simplified projection | Canonical page/detail load independently. Simplified access returns a typed unavailable response with generation/failure status. | Passed initial/later projection-failure regressions and browser acceptance |
| 4. Retained partial results hidden after failure | Failed create/refresh enters the best retained workspace, keeps a persistent failure banner, and reports phase, freshness, completed phases, and last-known-good status. | Passed API tests and real-browser current/stale/partial scenarios at 100%/200% |
| 5. Page-local search/focus | M10 now performs bounded server-side whole-graph search and exact focus, returning the page offset and element ID for results beyond the first 30 nodes. | Passed off-page search and exact ID/focus regressions; browser centered offset 150 |
| 6. Regions and proofs not inspectable | Region, fact, evidence, and proof IDs are detail targets and linked from node/edge detail. Nested-region continuations resume at the nested merge so enclosing-arm facts remain attached. | Passed synthetic nested-arm, detail, browser, and private attachment checks |
| 7. Proof contract mismatch | The contract now lists the implemented deterministic proof kinds for reachability, loops, terminals, call/return continuation, branch membership, and merge evidence. | Implementation, contract, and proof-set regression agree |
| 8. Private acceptance overstated | The harness uses actual game-folder ingestion, exact counts/rejoins/attachments, provider/network bombs, unchanged refresh reuse, fresh-project determinism, streamed payload hashes, and input immutability. | Passed in 305.082 s with measured evidence below |
| 9. Missing phase timing | Analysis-state schema 2 adds nonnegative completed- and failed-phase `duration_seconds`; timings remain outside normalized canonical bytes. | Passed nonnegative and structural-determinism regressions |
| 10. Opaque creator status unclear | Browser records expose `Unsupported creator Python · preserved, not executed` without fabricating an unresolved transfer. | Passed API and real-browser checks at 100%/200% |
| 11. M10 not the normal default | Browser selection order is current simplified M10, current canonical M10, coherent stale M10, then M07. AI remains selectable but does not override the M10 default. | Passed packaged-UI regression and real-browser default checks |

## Independently verified facts

The following facts are supported by direct repository inspection or focused regression work and
do not depend on the private MsDenvers environment:

- The correction baseline is the merged M10 `main` commit listed above.
- The source snapshot matches that baseline at the tracked-file blob level.
- M10 canonical reachability uses the resolved M06 graph and has explicit bounded proof records for
  reachable/unreachable status, loop membership, terminal classification, call-return
  continuation, branch-arm membership, and merge/region derivation.
- Canonical, simplified, and analysis-state payloads are checked for schema, source-generation,
  and canonical-hash coherence before inspection responses are served.
- Canonical inspection can return an available page/detail without a simplified projection.
- Whole-graph search/focus is bounded to 50 materialized matches while rendered pages remain at
  most 30 nodes and 180 edges.
- M10 detail can address regions, facts, evidence, and proofs directly.
- Nested branch-region traversal resumes after a nested merge without absorbing the nested body;
  enclosing-arm continuation facts therefore remain attached and inspectable.
- Operational completed- and failed-phase timing is stored in analysis state and excluded from
  canonical normalized structural bytes.

These facts do not replace the final command matrix below.

## Environment-specific validation

Environment-specific results identify the command, result, and measured timing from the final
Windows run against commit `92b67dc` plus the documentation-only working tree.

| Check | Result | Timing / artifact |
|---|---|---|
| Pre-fix focused M10 baseline | 25 passed | 3.24 s pytest |
| Regression-first reproduction | 5 expected failures before fixes | Regression commit `ea55c82` |
| Latest focused M10 suite | 43 passed | 4.84 s pytest; 5.350 s command elapsed |
| Full repository pytest suite on Windows | 590 passed | 61.21 s pytest; 61.678 s command elapsed |
| Ruff | Passed: `py -3.12 -m ruff check src tests scripts` | 0.165 s |
| Strict mypy | Passed: 62 source files | 0.230 s |
| `pip check` | `No broken requirements found.` | 0.459 s |
| Isolated wheel/package check | Build, isolated install, packaged import, and static-manifest presence passed | `renpy_story_mapper-0.1.0-py3-none-any.whl`; SHA-256 `B5E1B7FD41FF910F52D28F9CF250F54D6BC75CF587C556CDDFEB41F39E587458`; 7.054 s |
| Packaged JavaScript syntax checks | Four files passed `node --check` | 0.363 s |
| Browser acceptance at 100% | Passed current default, off-page search, direct detail, opaque status, stale fallback, canonical-only fallback, and bounded partial state | Combined artifact below; 16.579 s for both zooms |
| Browser acceptance at 200% | Passed the same matrix with 720x450 logical viewport, scale 2, and no horizontal-overflow offenders | `output/m10-browser-hardening-post-commit` |
| `git diff --check` | Passed; no whitespace errors | Final documentation tree |

The first baseline attempt without the repository `src` directory on `PYTHONPATH` collected an
older installed package and failed import collection. Re-running against this worktree's `src`
established the valid baseline above. This was an environment-selection issue, not a product
regression.

## Private MsDenvers acceptance

The private acceptance must be reported only from the actual supplied game folder or archive via
the normal ingestion/project-creation path. Recovered commercial source must not be committed.

| Required measurement | Result |
|---|---|
| Actual folder/archive ingestion | Passed through normal `game_folder` project creation and refresh; 52 authoritative recovered sources plus 5 secondary extras |
| Independent manifest fingerprint | Exact source `game/v0.01_clean.rpy`; SHA-256 `6dfe1bd2a6f05bc07c024ab29e3a64a465679eb0597c6a1c9ddb1b32806e21e8`; 33 independently checked lines |
| Expected choices / arms / exact rejoins | 4 choices, 8 ordered outcomes, 4 exact rejoin chains at lines 165, 233, 793, and 793 |
| Conditions/effects attached to expected edge, arm, or region | 5 conditions and 9 effects passed; 13 attach to expected branch arms and the later lust gate attaches to its canonical record |
| Canonical nodes / edges | 9,120 / 9,238 |
| Simplified nodes / edges | 418 / 553; manifest-source scope 68/100; whole-input projection is 4.583% of canonical nodes |
| Unchanged same-project refresh parsed / reused | 0 / 52; invalidated 0; removed 0 |
| Fresh-project canonical/projection structural determinism | Passed refresh and separate replay; canonical hash `1e3cfb3d764daa2860aeed6252d84e7ab423e884524c920a02829f4d9bba7a14`; projection hash `425aead9a9eae76942b1c6f624f057faa8150110a29109aa41d13782cffa8d51` |
| Provider constructions | 0, measured under a fail-fast construction bomb; deliberate-bomb regression passed |
| Remote requests | 0, measured under fail-fast socket/URL bombs; deliberate-bomb regression passed |
| Source/archive SHA-256 before and after | Source and `scripts.rpa` fingerprints unchanged; creator Python not executed; production hardcodes empty |
| Total and per-phase timings | First 69.570 s; refresh 151.404 s; replay 69.479 s; total 305.082 s. Phases: inventory 0.000389, parse 0.315447, graph 0.478959, semantic 2.131512, control flow 1.763942, route map 1.207367, canonical 43.334556, simplified 9.628225, inspection index 1.723687 s |
| Output report/artifact directory | `output/m10-private-msdenvers-hardening-final-passed` |

The previous merged report's constant `provider_calls: 0`, source-only ingestion, loose merge
reachability check, and fresh-project-only replay are not accepted as proof for this correction.

## Structural determinism and operational timing

The final run must compare normalized canonical and simplified structural bytes across a separate
fresh project created from unchanged input. It must also run an unchanged refresh on the same
project and report parsed, reused, and cache behavior. Nonnegative per-phase durations belong only
to operational analysis state and must differ without changing normalized canonical structural
bytes.

**Result: passed.** Same-project refresh and separate fresh replay produced identical canonical
and simplified hashes. Operational timing remained outside normalized structural bytes.

## Known unresolved behavior

- Arbitrary creator Python and dynamic transfers remain unsupported and unresolved where the
  deterministic analyzers cannot establish behavior. Creator Python is preserved and not executed.
- Reachability remains conservative. `possibly_dead` and
  `unreachable_in_resolved_static_graph` are not proofs of impossibility.
- A projection failure after a current canonical commit leaves simplified inspection unavailable
  until it is rebuilt; the current canonical graph remains usable.
- The simplified map is a structural inspection projection, not a human-authored scene or chapter
  map.
- Dense graphs remain bounded by deterministic paging and continuation behavior.
- The real game folder contains 52 authoritative recovered sources plus 5 secondary extras. Its simplified graph has 418 records even
  though the independently authored manifest source contributes 68 within the unchanged maximum
  of 100. The browser renders at most 30 nodes/180 edges; this correction does not add a lossy
  whole-project suppression heuristic merely to force the multi-source total below 100.
- Search uses deterministic metadata already present; it does not infer day/chapter boundaries or
  numbered-name/asset-name semantics.

## Explicitly deferred work

- **M11:** human narrative organization, scene/chapter boundaries, and semantic presentation work.
- **M12:** route-to-target solving, path feasibility, and guided route construction.
- **M13:** dynamic framework expansion and optional runtime-trace validation.

None of these deferred areas is implemented or claimed by this correction.

## Final diff summary

The correction changes 28 files with 3,781 insertions and 292 deletions over
`68923e494d3c8200514845191ced683239e714fc..HEAD`. Generated validation artifacts under `output/`
are intentionally untracked and excluded from this source diff.

## Changes made to this validation report

This correction replaces the merged report's overstatements with measured evidence:

- changed the baseline from M09 to exact merged M10 `main` commit
  `68923e494d3c8200514845191ced683239e714fc`;
- identified the correction branch and preserved regression-first commit history;
- added dispositions for all 11 post-merge findings;
- removed the claim that page-local filtering constituted whole-graph search/focus;
- removed the claim that node/edge detail alone made regions and proofs inspectable;
- removed the hardcoded zero-provider claim and made provider/network bombs mandatory evidence;
- distinguished recovered-source fingerprinting from actual folder/archive ingestion;
- required exact private rejoin evidence, explicit counts, attachment checks, unchanged refresh
  reuse, and separate fresh-project determinism;
- added phase timing and cross-generation pairing requirements;
- separated independently verified facts, environment-specific results, unresolved behavior, and
  M11/M12/M13 deferrals;
- replaced unrun command claims with the final Windows, browser, package, and private measurements;
- recorded the 52-source game-folder projection separately from the manifest-authored source
  scope instead of hiding either count.

## Proposed corrective pull request

Proposed title:

`Harden M10 generation integrity, inspection provenance, and acceptance`

Proposed body:

> ## Summary
>
> - compute canonical reachability from resolved M06 control flow, including synthetic return and
>   procedure-exit nodes, with explicit deterministic proofs;
> - prevent cross-generation canonical/projection composition and keep canonical inspection usable
>   when simplified projection creation fails;
> - surface retained current/stale results and failure context, with M10 inspection as the default;
> - add bounded whole-graph search/focus and inspectable region/fact/evidence/proof detail;
> - strengthen private acceptance around actual game-folder ingestion, exact rejoins, attachments,
>   refresh reuse, determinism, immutability, and fail-fast provider/network boundaries;
> - persist nonnegative operational phase timings without affecting structural determinism.
>
> ## Validation
>
> - Windows: 590 repository tests and 43 focused M10 tests passed; Ruff, strict mypy, `pip check`,
>   four JavaScript syntax checks, wheel build/install/import, and `git diff --check` passed.
> - Browser: the current, canonical-only, stale last-known-good, and bounded partial states passed
>   at 100% and 200%, including off-page focus and direct derivation detail.
> - Private: actual game-folder ingestion passed 4 choices, 8 arms, 4 exact rejoins, 14 facts,
>   unchanged refresh reuse, fresh replay determinism, input immutability, and measured zero
>   provider constructions/remote requests. Full measurements and artifact paths are in this
>   report.
>
> ## Boundaries
>
> This correction does not revert M10, reset to M09, rewrite history, or begin M11/M12/M13.
> Unsupported creator Python remains preserved and unexecuted; unresolved dynamic behavior remains
> conservative.

## Review gate

The corrected validation report is complete and internally consistent. Do not create the
corrective pull request yet; stop and wait for explicit approval.
