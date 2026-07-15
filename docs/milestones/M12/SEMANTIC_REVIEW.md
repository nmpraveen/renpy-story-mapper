# M12 semantic review

Date: 2026-07-15

Baseline: `fa8c543f648e085403f7448ab5e89f9b6e6c4fb6`

Decision: PASS

## Requirements

| Requirement / exclusion | Authority | Interpretation | Verified |
|---|---|---|---|
| M10-authoritative starting context | Approved amendment §2 | Accept only an M10 canonical node whose `reachability_witness.kind` is `root` and whose resolved-static proof is available, or a caller-supplied supported context bound to an exact M10 anchor | Yes |
| Context-specific destinations | Approved amendment §6 | Bind scene entry atoms, exact `CallSiteOccurrence` records, M11 temporary arms/persistent lanes, and M10 terminal/ending anchors; reaching another technical member of a scene is not completion | Yes |
| Conservative state and identity | Approved amendments §§5, 8 | Identify state by store/scope, variable name, and persistent status. Unknown M10 authority remains unknown and never becomes a default or proven range | Yes |
| Deterministic bounded solving | Approved amendments §§4, 9, 10 | Version expansion/frontier/prefix/depth/repetition/alternative/accounting limits in request identity; any deterministic or operational abort makes the solve incomplete | Yes |
| Internal prerequisites preferred | Approved amendment §7 | Attribute each requirement to one earlier proven effect, repetition count, explicit entry precondition, or unknown status; rank entry preconditions before commitments/loops/path length | Yes |
| M10/M11 authority unchanged | `MASTER_PLAN.md`; proposal | Consume exact canonical graph and scene-model records and persist only M12-derived results | Yes |
| Minimal deterministic UI | Approved amendment §11 | Add one route side panel to the existing browser and deterministic templates; reuse existing Detail/Evidence escape and navigation levels | Yes |
| Non-execution and privacy | `MASTER_PLAN.md`; proposal | Operate exclusively over persisted static records; never execute Ren’Py, game/creator code, providers, or remote requests; never mutate input roots | Yes |

## Architecture boundaries

- Authority and invariants: M10 owns canonical nodes, edges, facts, reachability, guards,
  effects, terminals, and provenance. M11 owns story-facing atom/scene order, occurrences,
  temporary outcomes, and persistent-lane interpretation. M12 may bind, traverse, abstract,
  rank, explain, cache, and export those immutable records but may not repair or reinterpret them.
- Components allowed to change: new M12 modules/tests/fixtures/acceptance, project persistence
  integration, bounded local API, and existing static browser surface.
- Components that must not change: M10 canonical/control-flow/state authority, M11 scene authority,
  original/private game inputs, provider contracts, and navigation hierarchy.
- External, privacy, safety, or platform boundaries: Windows CPython 3.12, loopback-only browser,
  no remote requests or code execution, qualified relative source evidence only.
- Starting context: the inspected M10 graph builder emits a root reachability witness for
  configured entry nodes and resolved-static reachability proof. That is sufficient authority for
  an M12 starting context. A merely named label or a dynamically possible entry is not sufficient.
- Destination binding: a generic scene binds its designated narrative entry candidates and records
  the actual selected occurrence. An exact shared-callee occurrence binds M11 caller scene/lane,
  `call_atom_id`, callee entry node, guards, and return context. Multi-entry scenes retain all valid
  candidates until the selected occurrence is known. Temporary outcomes and persistent lanes use
  their exact M11 records; terminal/ending targets use exact M10 terminal evidence.
- State timing: a fact may satisfy a later gate only when M10 provenance and traversal order prove
  that its effect occurs before that gate in the same structural/call context. Possible or unresolved
  writes never satisfy a requirement. M12 may compose call/return traversal context from exact M10
  call-site evidence but may not manufacture a canonical edge.
- Numeric abstraction: retain only target- and gate-relevant variables and comparison literals;
  threshold-equivalence classes are permitted only where all relevant operations preserve them.
  Exact values remain when equality, inequality, accumulated effects, or evidence needs them.
- Loop acceleration: require identical relevant transition summaries, structural and call-context
  return, no relevant one-shot/branch change, no possible relevant write, and proven repeated effect
  plus threshold. All other cycles use deterministic bounded traversal.
- Persistence: the existing payload transaction is atomic and checksum-versioned. M12 may add
  allowlisted scoped collections and a service-level result envelope without a schema migration.
  If implementation proves that indexed or cross-record atomic semantics cannot be represented,
  an M12-scoped migration is permitted and must be recorded before use.

## Expected files and tests

| Area | Expected files / components | Focused and regression checks |
|---|---|---|
| Model/solver | New M12 model, authority/destination mapping, abstract state, solver | New core tests; M10/M11 architecture regressions |
| Persistence | New M12 storage service or scoped migration plus project integration | Cache, migration, cancellation, atomic failure tests |
| API/UI/export | Existing local API/contracts/static files plus M12 adapter | API contracts, JS syntax, real browser, Detail/Evidence escape |
| Acceptance | New M12 fixtures and browser/scale/private harnesses | Fast/Focused/Release plus milestone-specific runs |

## Acceptance evidence plan

| Criterion | Proof required | Command or artifact |
|---|---|---|
| 1-4 | Exact bindings, start and destination mapping | Focused M12 authority tests |
| 5-11 | State/threshold/call/loop correctness | Focused M12 solver tests |
| 12-16 | Deterministic budgets, ranking, cache, failures | Focused scale/persistence/fault tests |
| 17-19 | UI, instructions, evidence, export, fixture matrix | API/browser/export tests and artifacts |
| 20 | Repository and private acceptance | Validation tiers, private report, review |

## Assumptions and conflicts

- M10 does not currently prove a complete store/scope/persistent/default-initialization identity for
  every variable. This is not a scope blocker because the amended contract explicitly requires a
  conservative unknown. M12 will preserve unknown identity fields, will not consume M09 literals as
  gate-proof authority, and will treat persistent values as external preconditions unless an exact
  M10 starting-context path proves the value.
- A proven literal assignment encountered on the selected M10 path may establish state from that
  point forward; a source-level default alone does not establish selected-context state.
- Unresolved dynamic transfer prevents a closed-world no-route result when it could reach the target.
  Lack of closed-world M10 evidence yields the dynamic/unknown result, never an M10 change.
- Proposed numerical defaults are implementation choices. The implementation must publish a
  versioned deterministic limit profile and include the complete profile in request/cache identity.
  Wall-clock time is an emergency abort only and is excluded from normalized result bytes.
- The current orchestration surface does not expose or verify model, reasoning-effort, or fast-mode
  selectors. The mandated worker setting therefore cannot be asserted here; this limitation is not
  product scope and will not create runtime checks.
- No authority or product-scope conflict was found.

## Gate decision

`PASS`: the repository exposes an M10-authoritative configured-entry root, exact M10 provenance and
control/state records, and sufficient M11 narrative/occurrence/lane records to implement every
approved target kind. Missing variable-identity and closed-world facts have an explicit conservative
representation and do not require changing M10 or M11. Broad implementation may begin.
