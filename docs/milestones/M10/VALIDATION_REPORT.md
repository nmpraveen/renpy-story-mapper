# M10.1 final hardening validation report

## Status and boundaries

- Baseline `main`: `7fd1604147afad2fa40a24c942dbe575aaef0f17`
- Branch: `codex/m10-final-hardening`
- Pull request: [#19](https://github.com/nmpraveen/renpy-story-mapper/pull/19)
- Final state: change-request corrections complete and ready for final review

The branch starts from the exact merged PR #18 baseline. It does not revert M10, reset to M09,
rewrite the accepted five commits, create a replacement pull request, or begin M11-M14.

Tracked `main` was clean and exactly matched `origin/main` before the branch was created. Existing
untracked user directories `docs/handoffs/` and `output/` were preserved. With the worktree `src`
directory selected on `PYTHONPATH`, the pre-fix focused M10 baseline was 43 passed in 4.91 seconds.
An earlier collection attempt selected an older installed package because `PYTHONPATH` was absent;
that environment error is not reported as a product regression.

## Reviewable commit structure

1. `dc55407` - `fix(m10): propagate branch guards and correct edge reachability`
2. `db304b0` - `perf(m10): bound reachability proof provenance`
3. `407e452` - `fix(m10): search suppressed canonical records from simplified view`
4. `3c860c2` - `perf(m10): reuse coherent unchanged analysis phases`
5. `9f33888` - `test/docs(m10): validate scale and restore the milestone roadmap`
6. `346ab71` - `fix(m10): close deterministic reachability gaps`
7. `test/docs(m10): record PR #19 change-request validation` - this report and roadmap update; its
   exact hash is supplied in the final handoff

The regression-first work remains visible inside these separate reviewable commits and must not be
squashed away before review.

## Regression-first evidence

| Finding | Observed before behavior changed | Corrected disposition |
|---|---|---|
| Impossible and unresolved `menu_no_choice` | The requested regression-first run proved an ordinary menu with an unconditional option could use `menu_no_choice` to mark `jump hidden`, `label hidden:`, and the hidden scene proven reachable. All-conditional no-choice predicates had no sibling requirement IDs, and menu set/custom availability was indistinguishable from ordinary availability. | Ordinary unconditional menus mark no-choice `impossible`, exclude it from resolved traversal, and make the fallback-only hidden path proven unreachable. All-conditional menus preserve ordered negative `conditions` with each sibling requirement fact. Set clauses and unsupported menu availability mark the edge and arm unresolved. |
| Ordered `if`/`elif`/`else` context | Multiple-`elif` regressions showed `elif beta` carried only positive `beta`, `elif gamma` only positive `gamma`, and `else` linked only the first sibling fact. Node, edge, arm, and region-detail assertions failed because the prior negative sibling context was absent. | Predicates carry ordered `conditions` records with expression, positive/negative polarity, branch order, and occurrence-specific requirement IDs: `+alpha`; `-alpha AND +beta`; `-alpha AND -beta AND +gamma`; and `-alpha AND -beta AND -gamma`. No textual Python negations are synthesized. |
| Guarded procedure entries | Guarded-only, multiple-caller, and nested-call regressions proved callee labels, bodies, returns, and shared procedure exits reachable without their caller guards. The regression file produced 11 failures before implementation. | Existing bounded guard states now rescope across resolved call entries and cross-label jumps. Unguarded entry alternatives still win, multiple guarded alternatives remain capped at eight, nested calls retain caller context, and existing call-summary/return-site isolation prevents guards crossing between callers. |
| Guarded reachability and edge status | The targeted regression run produced five failures: a guarded `secret` path and conditional menu body were proven reachable, a dead-source edge inherited its live target's status, and a guarded edge lacked conditional provenance. The initial unresolved assertion selected the wrong record by a generic `resolved` flag; selecting `kind == "unresolved"` proved unresolved behavior was already correct. | Ordered positive/fallthrough/menu predicates now retain M01/M02/M06 origin, polarity, branch order, requirement IDs, and bounded nested guard dependencies. Edge reachability derives from source, resolution, guard, and open-world status, with explicit proofs. |
| Quadratic reachability proofs | The new 2,000-statement scale regression failed with 4,008,004 reachability inputs and 111,896,575 normalized canonical bytes. | A deterministic BFS predecessor forest stores one root input or at most four ordered predecessor inputs per node. The final 2,000-statement result has 8,005 inputs and 6,255,798 canonical bytes. |
| Suppressed canonical search | Exact canonical ID, graph node ID, and source-text searches for suppressed `label dynamic_dispatch:` returned no simplified result; regressions failed with missing focus/metadata. | Search always scans bounded canonical authority. Represented matches focus their simplified representative; unrepresented suppressions switch to canonical, page to the bounded offset, and open the exact canonical record. |
| Unchanged refresh | The phase/backup bomb regression failed immediately in `Project.backup`; the unchanged path staged a full database and reran every deterministic phase. | Reuse requires exact source/dependency identity, entry/options/roles, supported schemas, current-complete phase bindings, coherent canonical/projection/route hashes, route checkpoints, metadata dependencies, and presentation generation. Valid reuse performs no writes or backup and reports all reused phases; incoherent state follows the existing staged recomputation path. |
| Headless private safety boundary | A subprocess with `PySide6` imports blocked failed while importing `m10_private_acceptance.py`, before provider/network bombs could be installed. | The harness no longer imports the Qt-backed provider. Its offline boundary injects a provider sentinel module; the headless subprocess and deliberate provider/network bomb regressions pass. |

The exact PR #19 change-request regressions are:

- `test_unconditional_menu_no_choice_cannot_reach_a_hidden_scene`
- `test_all_conditional_menu_no_choice_links_negative_sibling_requirements`
- `test_menu_no_choice_with_unresolved_availability_stays_unresolved` for both `set seen` and a
  custom menu header
- `test_ordered_if_predicates_preserve_all_prior_sibling_conditions`
- `test_ordered_elif_context_is_preserved_in_node_edge_arm_and_region_details`
- `test_guarded_only_call_keeps_the_callee_conditional`
- `test_unguarded_call_or_jump_makes_a_shared_callee_proven` for both call and jump entry
- `test_multiple_guarded_callers_retain_bounded_entry_alternatives`
- `test_nested_guarded_calls_propagate_the_entry_context`
- `test_return_continuations_remain_isolated_by_call_site`

## Delivered behavior

- Impossible ordinary-menu no-choice edges no longer participate in resolved static reachability;
  set/custom availability stays explicitly unresolved.
- Ordered branch and conditional no-choice predicates expose structured `conditions`, `operator`,
  polarity, branch order, and all linked sibling requirement facts.
- Procedure-entry guards propagate across guarded calls and nested calls with at most eight stored
  alternatives; unguarded calls/jumps win, while return continuations remain call-site-specific.
- True/false/fallthrough and conditional-menu predicates are structurally distinct; no unsafe
  textual negation is invented.
- Temporary guards stop at proven merges, persistent guards continue through owned members,
  nested regions accumulate without flattening, and an unguarded alternate path still wins.
- Dead-source, conditional, resolved call/return, and unresolved edge statuses remain coherent.
- Proof `input_ids` are ordered, order participates in identity, and predecessor witnesses permit
  lazy path reconstruction with linear total storage.
- Simplified search returns matched record kind/ID, canonical ID, target view, bounded offsets,
  canonical fallback target, and visible simplified representative when one exists.
- Unchanged folder, archive, and unified-input refreshes reuse all coherent deterministic phases,
  skip presentation rebuild and the SQLite staging backup, and return `reused_phases`.
- The stale AI-default toast now states that an applied AI Story Map is ready to review.
- The roadmap assigns M11 to human scenes/chapters, M12 to route solving and path requirements,
  M13 to the AI narrative layer, and indefinitely deferred M14 to dynamic adapters/tracing.

## Final Windows validation matrix

| Check | Result | Timing / artifact |
|---|---|---|
| Pre-fix focused M10 baseline | 43 passed | 4.91 s pytest |
| PR #19 change-request regression-first run | 11 failed, 18 passed before implementation | Exact failures covered menu feasibility, ordered branch context, guarded callees, bounded alternatives, nested calls, and return isolation |
| Final canonical defect regression file | 29 passed | 0.40 s pytest |
| Final full repository pytest | 615 passed | 68.39 s pytest with fixed `PYTHONHASHSEED=0` |
| Final focused M10 pytest | 68 passed | 7.06 s pytest |
| Synthetic hidden-gate/menu/dead-edge/alternate-path acceptance | 4 passed | 0.07 s |
| Ruff | Passed for `src tests scripts` | Final command exit 0 |
| Strict mypy | Passed for 61 source files | Final command exit 0 |
| `pip check` | No broken requirements | Final command exit 0 |
| JavaScript syntax | `api.js`, `app.js`, `contract.js`, and `graph.js` passed `node --check` | Final command exit 0 |
| Wheel build/install/import/static assets | Passed in isolated target | 387,677-byte wheel; SHA-256 `3f0472b562f03e5718ee27e0bdfa86d97f6c28b7a44601d97f4b8b5164248123` |
| Browser acceptance | Passed at 100% and 200%; no overflow, provider construction, or remote request | `output/m10-pr19-review-fixes/browser-final` |
| Persisted linear scale acceptance | Passed all proof/payload growth bounds | `output/m10-pr19-review-fixes/scale-final` |
| Private actual-folder acceptance | Passed exact choices/rejoins/facts, determinism, bombs, and immutability | 52.348 s; `output/m10-pr19-review-fixes/private-final` |
| Source/archive immutability | Source and `scripts.rpa` SHA-256, size, and modification time unchanged | Private report |
| Structural determinism | Same-project refresh and separate fresh replay hashes equal | Private report |
| Provider/network boundary | 0 provider constructions; 0 remote requests | Private report and deliberate-bomb tests |

Two initial full-suite attempts completed with 614 passing tests and only the pre-existing M06
10,000-node two-second timing threshold above its limit while the machine was cold (2.24-2.47 s).
The unchanged timing test then passed repeatedly in isolation at 1.87-1.90 s; no threshold or M06
algorithm was changed. The final fixed-seed complete run passed all 615 tests in 68.39 s.

## Linear proof/storage measurements

The pre-fix reproduction and the bounded in-memory implementation used the same deterministic
linear-script helper:

| Statements | Pre proof inputs | After proof inputs | Pre canonical bytes | After canonical bytes | Pre build + serialize | After build + serialize |
|---:|---:|---:|---:|---:|---:|---:|
| 500 | 252,004 | 2,005 | 8,102,321 | 1,565,274 | 0.202784 s | 0.081082 s |
| 1,000 | 1,004,004 | 4,005 | 29,449,075 | 3,124,778 | 0.634286 s | 0.169003 s |
| 2,000 | 4,008,004 | 8,005 | 111,896,575 | 6,247,778 | 2.209597 s | 0.370775 s |

The final persisted-project acceptance, which also includes the current ingestion and database
layout, measured:

| Statements | Nodes / edges | Proof inputs | Canonical bytes | SQLite bytes | Canonical phase | Total analysis |
|---:|---:|---:|---:|---:|---:|---:|
| 500 | 502 / 501 | 2,005 | 1,566,789 | 3,637,248 | 0.115413 s | 0.465888 s |
| 1,000 | 1,002 / 1,001 | 4,005 | 3,128,798 | 6,803,456 | 0.232957 s | 0.684923 s |
| 2,000 | 2,002 / 2,001 | 8,005 | 6,255,798 | 13,201,408 | 0.508299 s | 1.346132 s |

The 500-to-1,000 persisted payload ratio is 1.996949x. The 2,000-statement payload is below 12 MB
and total reachability inputs remain below four times the node count. The earlier approximately
112 MB 2,000-statement SQLite result is replaced by the exact 13,201,408-byte persisted result.

## Private MsDenvers before/after evidence

The final run used the normal actual game-folder ingestion path, 52 authoritative recovered
sources plus 5 secondary extras, and the independently authored Day 1 ground truth. It verified 4
choices, 8 ordered outcomes, 4 exact rejoin chains, 5 conditions, 9 effects, and 1 visibility case.

| Measurement | Accepted PR #19 head before review fixes | Final PR #19 review fixes |
|---|---:|---:|
| First analysis | 13.280 s | 23.041 s |
| Canonical phase | 4.847168 s | 11.139397 s |
| Unchanged refresh | 0.805 s | 1.427 s |
| Fresh replay | 12.973 s | 23.408 s |
| Canonical payload | 36,537,547 bytes | 161,312,664 bytes |
| Simplified payload | 1,800,115 bytes | 1,857,276 bytes |
| SQLite project | 110,247,936 bytes | 235,261,952 bytes |

The unchanged refresh parsed 0 and reused 52 sources. Under fail-fast backup and phase bombs it
reused, in order: `source_inventory`, `parse`, `graph`, `semantic_state`, `control_flow`,
`route_map`, `canonical_graph`, `simplified_projection`, and `inspection_projection`.

The larger canonical payload is the cost of retaining structured ordered sibling predicates and
bounded guarded procedure-entry provenance throughout callees. The 9,120-node/9,238-edge private
graph remains deterministic, the unchanged path still performs no phase recomputation, and the
separate 2,000-statement scale harness remains below every existing growth bound.

Canonical and simplified hashes were stable across unchanged refresh and a separate fresh replay:

- canonical: `769c2931f284fa875a0b8d561d668fcfe21c4d7e0de83c3f09fad71e7d5f6a2f`
- simplified: `e8cf9abb2db486dedb5937e52414dff3cde78fdfa4d36d2a9d4d3609237b26cc`

The source and archive retained identical SHA-256, size, and modification time. Creator Python was
not executed, production game-specific hardcodes were absent, provider constructions were 0, and
remote requests were 0.

## Known unresolved behavior

- Arbitrary creator Python, computed transfers, and unsupported dynamic framework behavior remain
  conservative and unresolved; no satisfiability engine was introduced.
- Guard propagation is bounded to deterministic M06 region/edge evidence and representative guard
  states. Procedure-entry alternatives are capped at eight and rescope existing guard tokens rather
  than enumerating complete paths or predicate combinations.
- Search materializes at most 50 results and rendered pages remain at most 30 nodes and 180 edges.
- An existing project created before the dependency-identity metadata was introduced performs one
  normal staged refresh before it becomes eligible for the no-write fast path.
- The simplified inspection remains structural, not the M11 human scene/chapter model or the M13
  AI narrative layer.
- Dynamic framework adapters and optional runtime tracing remain deferred indefinitely to M14.

## Corrected roadmap

- **M11:** human story scenes and scene/chapter presentation.
- **M12:** route-to-target solving and path requirements.
- **M13:** optional AI narrative titles, summaries, characters, motives, and
  chapter/route/full-plot summaries.
- **M14:** dynamic framework adapters and optional runtime tracing, deferred indefinitely for now.

## Current pull request #19

Proposed title:

`Harden M10 guarded reachability, canonical search, and unchanged refresh`

Proposed body:

> ## Summary
>
> - make ordinary unconditional-menu no-choice edges impossible, preserve structured negative
>   sibling requirements when all choices are conditional, and keep set/custom availability
>   unresolved;
> - preserve complete ordered `if`/`elif`/`else` contexts as structured expression/polarity records
>   with every corresponding requirement fact;
> - propagate bounded guard alternatives through call and nested-call entries while preserving
>   unguarded dominance and call-site-specific return continuations;
> - preserve ordered branch/menu predicate provenance and propagate bounded guard dependencies
>   through M06 branch arms;
> - derive edge reachability from the source, resolution, guards, and open-world status instead of
>   inheriting a target reached by another path;
> - replace duplicated full reachability paths with ordered constant-size BFS predecessor
>   witnesses;
> - search bounded canonical authority from either view, focusing a simplified representative or
>   switching to exact canonical detail for an unrepresented suppression;
> - reuse all deterministic phases on a fully coherent unchanged refresh without a staging backup
>   or presentation rebuild, while falling back safely on any coherence failure;
> - keep private acceptance headless, fail-fast, and measurable, and restore the M11-M14 roadmap.
>
> ## Validation
>
> - Windows: 615 repository tests and 68 focused M10 tests passed; Ruff, strict mypy, `pip check`,
>   four JavaScript syntax checks, wheel build/install/import, and whitespace checks passed.
> - Browser: 100% and 200% acceptance passed, including suppressed canonical auto-switch/direct
>   detail, bounded paging, retained failure states, and zero remote requests.
> - Scale: the persisted 2,000-statement project has 8,005 reachability inputs, a 6,255,798-byte
>   canonical payload, and a 13,201,408-byte SQLite database; 500-to-1,000 payload growth is
>   1.996949x.
> - Private: actual-folder acceptance passed exact choices/rejoins/facts, separate-replay
>   determinism, source/archive immutability, and measured zero provider constructions/remote
>   requests. Unchanged refresh completed in 1.427 s while reusing all nine phases under fail-fast
>   phase and backup bombs.
>
> ## Boundaries
>
> This correction keeps PR #18 intact, does not reset to M09 or begin M11-M14, and does not add a
> theorem engine, game execution, or runtime tracing. Unsupported dynamic behavior remains
> conservative and unresolved.

## Stop condition

The corrected validation report is complete. Push these corrections to existing PR #19 and stop
for final review. Do not create another pull request, merge PR #19, or begin M11.
