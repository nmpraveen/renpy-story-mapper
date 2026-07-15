# M12 - Route-to-target solving and path requirements

Status: PR ready

Scope authority: `docs/MASTER_PLAN.md`, M12 approved proposal, and the user's 2026-07-15
binding amendments

Baseline: `fa8c543f648e085403f7448ab5e89f9b6e6c4fb6`

Validated product head: `1df83098872fb63d434ff3e59a79e0f286944260`

## Done condition

M12 is PR-ready when, from an existing M10-authoritative project entry or supported starting
context, a user can select a supported M11/M10 destination and receive an on-demand,
deterministic, bounded, cacheable best-known route containing ordered human scenes, visible
choices, deterministically templated instructions, conservative state feasibility, exact
M10/M11 provenance, expandable evidence, safe cancellation, and honest unresolved
behavior—without executing Ren’Py, the game, creator code, a provider, or a remote request.

## Objective

Add a conservative target-specific solver and compact browser workflow over existing M10 graph
authority and M11 human-scene targets. The result must explain prerequisites and their provenance
without enumerating playthroughs, inventing state, or claiming unsupported satisfiability.

## Deliverables

- Exact authority binding and destination mapping for generic scenes, exact call-site
  occurrences, temporary outcomes, persistent lanes, terminals/endings, and repeatable events.
- A deterministic, bounded solver with supported initial/abstract state, call context, loop
  handling, conservative statuses, one recommended route, and explainable ranking.
- Deterministically templated instructions separating assumptions, scenes, choices, repeated
  actions, requirements, satisfying effects, commitments, and uncertainty.
- Versioned atomic route persistence, exact-key cache reuse/invalidation, cancellation, isolated
  attempt diagnostics, and preservation of M10/M11 data on failure.
- A bounded Route Map side panel with destination search, four simple badges, technical status,
  expandable evidence, and direct escape to existing Detail/Evidence.
- Bounded materially different alternatives, versioned JSON export, and thin deterministic
  Markdown formatting if correctness is not delayed.
- Synthetic, regression, persistence, fault-injection, scale, browser, and private acceptance
  evidence plus the required milestone reports and native infographic.

## Acceptance criteria

1. Every solve binds the exact M10 source generation/schema/hash, M11 schema/model hash,
   destination, solver version, and deterministic option/budget identity; identical inputs yield
   byte-identical normalized results that exclude volatile metrics.
2. M10 remains the sole authority for structure, reachability, conditions, effects, calls,
   returns, loops, regions, terminals, and unresolved behavior; M12 changes no M10/M11 authority.
3. A safe start comes only from M10 configured-entry root evidence or an explicitly supported
   starting context. Missing start authority produces a conservative failure, never an invented
   entry.
4. Destination mapping supports generic scenes, exact scene/call-site occurrences, temporary
   outcomes, persistent lanes, M10 terminals/static endings, and repeatable events reached at
   least once. Scene completion requires a verified narrative/occurrence anchor, and a generic
   shared scene reports the actual occurrence selected.
5. State-variable identity contains store/scope, variable name, and persistent status, including
   explicit unknown values where M10 lacks authority. Known initial values, external entry
   preconditions, and unknown initial values remain distinct.
6. Only M10-proven literal initialization/effects satisfy gates. Unknown booleans/numbers and
   persistent variables are never assigned assumed values; possible/unsupported effects never
   satisfy requirements.
7. The target-relevant numeric abstraction preserves exact values when required and otherwise
   uses sound threshold-equivalence classes without retaining unrelated numeric state or losing
   effect-before-gate timing.
8. Every material requirement links to exactly one earlier satisfying proven effect, proven
   repeated-event count, explicit entry precondition, or unknown/unsupported status. Internally
   achieved prerequisites rank ahead of equivalent entry assumptions.
9. Structural path, accumulated requirements, known effects, unresolved/conflicting facts, and
   conservative state feasibility remain separate result dimensions; supported contradictions
   and effects occurring too late are detected with exact evidence.
10. Call traversal preserves caller, call-site, guard, callee, and return context. Shared callees
    never imply false route reunion, and exact occurrence destinations remain context-specific.
11. Loops are accelerated only when every approved safety condition holds. Other loops are
    bounded; any loop/repetition or deterministic search bound yields an incomplete solve and
    cannot prove no-route or state-infeasible.
12. The solver is destination-specific, avoids all-target/playthrough preprocessing and Cartesian
    choice expansion, reuses shared prefixes/commitments, and enforces versioned deterministic
    expansion, frontier, retained-state, prefix, call-depth, loop, alternative, and memory/account
    limits included in cache identity.
13. A wall-clock abort is emergency-only: it creates an uncached attempt diagnostic, publishes no
    normalized result, preserves prior cache entries, and cannot support reachability,
    infeasibility, or reproducibility conclusions.
14. Confirmed, prerequisite, best-known, state-unknown/infeasible, no-static-route,
    dynamic-possibility, and incomplete outcomes obey their conservative evidence invariants.
    Negative conclusions require exhaustive completion under the supported abstraction and exact
    closed-world/contradiction evidence.
15. Ranking is deterministic and explainable, prioritizing unresolved behavior, inferred or
    unsupported assumptions, external entry preconditions, persistent commitments, loop count,
    meaningful human-scene length, and stable source/identifier tie-breakers. One correct
    recommended route is delivered before alternatives.
16. Successful route results are atomically versioned and cached by exact request identity;
    stale bindings invalidate safely, cache hits avoid solving, failed destinations retry
    independently, and cancellation/failure cannot alter M10/M11 or replace a valid result.
17. The browser implements the minimal select → “How do I reach this?” → ordered route → evidence
    flow with Confirmed route, Route with prerequisites, Best known route, or No proven route
    badges, without a third navigation level or interpretation pipeline.
18. Every material route claim carries exact M10 evidence/proof and M11 provenance where human
    presentation is used. Detail expansion and JSON/optional Markdown export remain bounded,
    deterministic, path-safe, and free of bulk copyrighted content.
19. Direct tests cover all submitted proposal fixtures plus literal initialization, unknown and
    persistent state, scoped same-name variables, internal-prerequisite ranking, exact/generic
    shared occurrences, repeatable targets, deterministic budget replay, uncached emergency
    abort, volatile-byte exclusion, threshold abstraction, multiple increments/thresholds,
    unsafe one-shot loops, multi-entry scenes, templated instructions, and conservative negative
    results.
20. Full M10/M11 regressions, Windows validation tiers, scale/browser/persistence/fault/private
    acceptance, zero provider/network/game execution, and input immutability pass with durable
    evidence and no unresolved blocking review finding.

## Required evidence

| Criterion | Evidence required | Result / durable location |
|---|---|---|
| 1-4 | Binding, entry, destination, determinism, and authority contract tests | Pass; focused M12 suite and `VALIDATION_REPORT.md` |
| 5-11 | State, call-context, timing, loop, threshold, and contradiction fixture tests | Pass; focused M12 suite and named fixtures in `VALIDATION_REPORT.md` |
| 12-15 | Budget replay, ranking, alternatives, status, and scale metrics | Pass; byte-identical scale runs in `VALIDATION_REPORT.md` |
| 16 | Cache/write counters, migration/open behavior, cancellation and injected failures | Pass; 32 persistence/fault/private-harness tests and emergency replay evidence |
| 17-18 | API/real-browser checks, screenshots, bounded provenance traversal, export hashes | Pass; Chrome 100%/200% artifacts and hashes in `VALIDATION_REPORT.md` |
| 19 | Named synthetic test matrix with commands and counts | Pass; 97 focused M12 tests, one opt-in browser skip exercised separately |
| 20 | Fast/Focused/Release, private fingerprints, review, completion, and PR state | Pass; approval-gated PR #22 is open and unmerged; see `COMPLETION_REPORT.md` |

## Exclusions

- No AI route correctness, titles, summaries, motives, themes, plot interpretation, graph
  generation, walkthrough prose generation, or global AI stitching.
- No runtime tracing, dynamic-framework adapters, arbitrary Python/expression evaluation, Ren’Py
  execution, creator/game/screen execution, automatic game control, or save-file changes.
- No playthrough enumeration or Cartesian expansion of independent choices.
- No M11 boundary retuning, M11 review reopening, or changes to M10/M11 authority to fit M12.
- No PDF/polished walkthrough publishing, separate export pipeline, third navigation level,
  installer, packaging, hosted service, or unrelated UI redesign.
- No access to private acceptance inputs before the bounded acceptance stage; never record their
  machine path or commit copyrighted content.
- No M13 work and no merge of the M12 PR without explicit user approval.

## Handoff rules

- Provide the exact base/result commits, branch or worktree, changed files, validation commands
  and results, assumptions, known defects, conflicts, and remaining acceptance work.
- Give each worker exclusive owned files, literal base commits, dependencies, exclusions, and
  required checks. No worker opens a PR.
- Use at most the primary orchestrator plus two concurrent workers. Integrate only on
  `codex/m12-route-solving`.
- Keep status at `Verification` until all evidence is committed and the approval-gated PR exists.
- Keep the native Codex goal active through integration, verification, private acceptance,
  review, evidence, and PR preparation. Complete it only at genuine `PR ready`.
