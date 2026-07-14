# M10 canonical graph contract

- Status: corrected post-merge implementation contract
- Canonical schema: `m10-canonical-graph-v1`
- Analysis-state schema: `2`

## Purpose and authority

The M10 canonical graph is an immutable derived read model over existing deterministic records.
It is not an independent mutable source of truth. Every canonical record references its M01, M02,
M06, M07, state, gate, effect, unresolved, or source record of origin. Existing parsing,
call/return, dominator, post-dominator, loop, branch-region, and route-classification algorithms
remain the factual authority.

M10 does not execute creator Python, consult a provider, infer semantic scene boundaries, enumerate
playthroughs, or solve routes to a target.

## Record kinds

Canonical node kinds are `label_region`, `script_unit`, `choice`, `condition`, `merge`, `loop`,
`terminal`, and `unresolved`. A node may reference more than one origin record when it normalizes
an existing deterministic projection.

Canonical edge kinds are `entry`, `flow`, `choice`, `condition`, `call_enter`, `call_return`,
`call_summary`, `jump`, `loop_body`, `loop_back`, `loop_exit`, `terminal`, and `unresolved`. These
are normalized from M06 `FlowEdgeRole`; M10 does not infer new control flow.

Canonical region kinds are `local_detour`, `optional_detour`, `reconvergent_route_segment`,
`persistent_route`, `terminal_split`, `loop_choice`, and `unresolved`. These are normalized from
M06 `RouteClassification` without changing membership or proof.

## Stable identities and origins

Canonical IDs are SHA-256-derived from the schema version, record kind, and sorted stable origin
record IDs. An origin reference is `(collection, record_id)` and may include an origin subpath.
IDs do not depend on iteration order, timestamps, run IDs, output directories, or phase timing.
For unchanged input and schema version, structural IDs and normalized serialization are stable.

The payload carries a source-generation identity: the SHA-256 digest of the canonical ordered
source fingerprint set. Every origin phase used to build the payload declares the same generation.
Cross-generation composition is invalid.

## Evidence and deterministic derivation

Direct source evidence contains a stable evidence ID, relative source path, exact source span,
source text, line-basis/provenance fields when available, and origin references.

Every canonical node and edge has at least one of:

1. one or more direct source-evidence IDs; or
2. a deterministic proof record with a stable ID, proof kind, ordered input values, origin
   references, and a bounded explanation.

The implemented proof kinds are:

- `normalized_control_edge`
- `synthetic_control_node`
- `resolved_static_reachability`
- `scc_loop_membership`
- `terminal_classification`
- `call_site_return_continuation`
- `branch_arm_membership`
- `immediate_post_dominator_merge`
- `branch_region` when no immediate post-dominator merge exists

These are bounded provenance records over deterministic M06 outputs, not a generic theorem system.
They do not claim arbitrary expression satisfiability.

## Resolved static reachability

Reachability is computed over the normalized M06 control graph, not copied from an M01 raw node.
Traversal begins at the M06 procedure entry for the configured entry label, with an M06 label-node
fallback when a procedure entry is unavailable. It follows only resolved, non-`unresolved` M06
edges. Synthetic M06 nodes, including procedure exits and return sites, participate in the same
traversal.

M01 reachability may appear as supporting evidence but is not the authority for M06-only nodes.
For every node classified from a known entry, `resolved_static_reachability` records the entry
origin and the deterministic M06 path inputs. Resolved edges derive their status coherently from
their resolved endpoints and existing requirement facts.

Statuses are assigned conservatively and in this order:

| Evidence | Status |
|---|---|
| Item is itself unresolved or depends on an unresolved transfer | `unresolved_dynamic_behavior` |
| Reachable in the resolved static graph and guarded by a supported proven requirement | `conditionally_reachable` |
| Reachable in the resolved static graph and guarded only by possible or inferred requirements | `reachable_under_inferred_requirements` |
| Reachable in the resolved static graph without a known gate | `proven_reachable` |
| Not statically reachable and an unresolved dynamic transfer could reach it | `possibly_dead` |
| Not statically reachable and the resolved static graph is not closed for another reason | `unreachable_in_resolved_static_graph` |
| Not statically reachable, the supported graph is closed, and no unresolved transfer can reach it | `proven_unreachable` |

Unsupported creator Python, dynamic jumps, custom screens, unknown registries, and unresolved
dispatch prevent a closed-world impossibility claim where they can affect the result.

## Canonical and simplified generation pairing

The canonical payload is independently usable. The simplified projection is optional and may be
served only when all of the following hold:

- its schema is `m10-inspection-projection-v1`;
- `projection.source_generation == canonical.source_generation`;
- `projection.canonical_graph_hash` equals the SHA-256 of the selected canonical payload; and
- the analysis state identifies the selected generation and its current or stale availability.

If a refresh fails before a new canonical graph is committed, the retained old canonical and
simplified payloads remain one coherent stale pair. If a new canonical graph is committed and its
simplified projection then fails, the current canonical graph remains usable and the old simplified
projection is reported as unavailable; it is never combined with the new canonical graph.

The analysis state schema and its selected canonical generation/hash are validated before its
freshness metadata is trusted. The state has status `stale`, `current_partial`, `current_complete`, or `failed`.
Canonical availability is `none`, `stale`, or `current_complete`. Simplified availability is
`none`, `stale`, `current_complete`, or `unavailable`. A failure record contains the sanitized
failed phase, code, message, and nonnegative `duration_seconds`. Each completed phase records its
source generation, persisted payload bindings, and a nonnegative `duration_seconds` value.

## Serialization

Normalized canonical serialization is UTF-8 JSON with sorted keys, compact separators, finite
JSON values, and records sorted by stable ID. It includes schema version, source generation,
structural records, evidence references, origins, proofs, and reachability. It excludes timestamps,
durations, run IDs, transient errors, absolute output paths, and other operational metadata.
Operational phase durations therefore do not affect canonical structural determinism.

## Inspection and suppression

The canonical graph never deletes aliases, technical corridors, support-only terminals, or raw
branch members for presentation reasons. Simplified projection records may suppress or collapse
them, but retain canonical member IDs and canonical escape IDs.

Branch-region detail exposes classification, split, ordered arms, arm entry and member counts,
merge/rejoin when present, persistence reasons, unresolved/terminal summaries, attached gate and
effect facts, origins, proofs, and canonical escape IDs. Facts, evidence, proofs, and regions are
also addressable as detail records. This is inspection provenance only; route-to-target solving is
deferred to M12.

For nested regions, direct outer-arm ownership skips the nested body but resumes at the nested
split's immediate post-dominator. Continuation nodes and their facts therefore remain attached to
the enclosing arm without flattening nested ownership.
