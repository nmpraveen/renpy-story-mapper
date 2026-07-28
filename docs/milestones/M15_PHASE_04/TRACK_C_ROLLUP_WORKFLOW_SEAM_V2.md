# Phase 04 Track B/C derived semantic workflow seam v2

Status: Frozen scalar integration contract

Version: `story-map-v2-derived-semantic-workflow-v2`

Supersedes the preliminary `story-map-v2-rollup-workflow-v1` at `9657c6e`. The rejected v1 remains
durable history; it incorrectly assumed that exact derived request children could be frozen at
Prepare before mapper/section outputs exist. This v2 contract freezes exact upper bounds and a
dependency plan at Prepare, then registers immutable exact-input jobs only as their children
publish. Track B imports no C1 or reader type.

## Provider call kinds

Add exactly:

- `ProviderCallKind.SECTION_SYNTHESIS = "section_synthesis"`
- `ProviderCallKind.ROLLUP_SYNTHESIS = "rollup_synthesis"`

A rollup job separately carries scalar `node_role` with exactly one of `route_reduction`,
`route_summary`, `whole_game_reduction`, or `final_overview`. Mapping, replacement review, and
refusal fallback remain unchanged. Node roles are metadata, not additional provider call kinds.

## Frozen Prepare descriptor

Persist one provider-neutral `WorkflowDerivedSemanticPlanDescriptor` beside the unchanged
`WorkflowPlanDescriptor.jobs`. It contains:

- `semantic_plan_identity`: canonical descriptor hash
- `story_chunk_plan_identity`
- `authority_identity`
- ordered corridor descriptors containing `corridor_id`, nullable `route_owner`,
  `event_slot_upper_bound`, and `ordinal`
- persistent route memberships
- `fan_in = 24`
- every exact maximum count below

The exact section/rollup serialized request bytes and ordered child IDs depend on validated
mapper/section outputs and therefore must not be guessed at Prepare. Later jobs are immutable
dependency-created jobs in the same run/accounting repository. Each binds
`semantic_plan_identity`, `candidate_generation_identity`, `job_id`, `call_kind`, nullable
`node_role`, nullable `corridor_id`, nullable `route_owner`, exact ordered `child_ids`, `ordinal`,
and `SerializedRequestIdentity`. These jobs neither mutate nor join the frozen mapping-jobs tuple.

## Exact finite ceilings

Let `U_c` be the frozen maximum possible sections in corridor `c`: one per exact mapped or
fallback event slot. Let `U_r = sum(U_c)` for corridors owned by persistent route `r`,
`U_common = sum(U_c)` for nonpersistent corridors, `R` be the number of nonempty persistent
routes, and `F = 24`.

Define:

```text
reduce(n) = 0                                      when n <= F
reduce(n) = ceil(n / F) + reduce(ceil(n / F))     when n > F
```

The frozen Prepare ceilings are:

- `section_synthesis_calls = C`, where `C` is the number of nonempty corridors.
- `route_reduction_calls = sum(reduce(U_r))` across persistent routes.
- `route_summary_calls = R`; every persistent route has one AI route-summary slot even with one
  child.
- `whole_game_reduction_calls = reduce(U_common + R)`.
- `final_overview_calls = 1` when `U_common + R > 0`, otherwise `0`.
- `rollup_synthesis_calls` equals the exact sum of the preceding four rollup fields.

The actual fixed-membership DAG is derived deterministically from accepted-or-fallback sections
using consecutive groups of at most 24 and may consume fewer calls than these maxima. Registration
or reservation above any individual field or the rollup total is rejected transactionally. There
is no adaptive splitting.

## Exact input and cache identity

Canonical requests bind `semantic_plan_identity`, `story_chunk_plan_identity`,
`authority_identity`, `candidate_generation_identity`, job ID, call kind, node role, corridor and
route ownership, exact ordered child IDs and their normalized prose hashes, prompt/schema/adapter
versions, provider, model, reasoning, fast mode, and cloud mode. The existing
`ProviderInputIdentity` and cache rules additionally bind exact serialized bytes, hash, and byte
count. Only run/lease routing is excluded.

Both new call kinds are cloud-only `codex-cli` / `gpt-5.6-terra` / High / fast mode off, with
separately versioned section and rollup prompt/schema/adapter IDs. Neither kind permits replacement
review or loopback fallback. Invalid, foreign, reordered, incomplete, or route-crossing output
falls back structurally at that exact node with zero further provider calls.

## Dependency, retry, cancellation, and reads

Track B provides generic derived-semantic-plan persistence in the preview, the two enum values,
the exact ceiling/accounting/reservation fields, immutable dependency-job registration after
children publish, dependency-ready claiming, and transactional per-field maximum enforcement.
Existing attempt/cache/cancel/recovery semantics are reused without C1 imports.

- Reserve durably before possible transmission.
- Persist cancellation before transport signalling and never start descendants afterward.
- Definite non-transmission remains resumable under unchanged approval and identical input/call
  kind with a new attempt ordinal; it does not consume transmitted-call capacity.
- Indeterminate transmission is terminal and never auto-resubmits. One retry requires exact
  job-specific approval for the identical request under the existing finite supplemental
  indeterminate-retry ceiling.
- Invalid transmitted output never retries.
- Cancelled runs remain terminal.
- Reopen, status, and every read construct zero providers.

Reader contract v2 remains unchanged. Workflow HTTP status exposes exact derived `job_id`,
`attempt_id`, and call kind for indeterminate work through the separate Track B-owned HTTP domain
contract.
