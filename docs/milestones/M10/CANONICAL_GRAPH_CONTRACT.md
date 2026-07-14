# M10 canonical graph contract

Status: approved implementation contract  
Schema: `m10-canonical-graph-v1`

## Purpose and authority

The M10 canonical graph is an immutable derived read model over existing deterministic records.
It is not an independent mutable source of truth. Every fact must reference its M01, M02, M06,
M07, state, gate, effect, unresolved, or source record of origin. Existing parsing, call/return,
dominator, post-dominator, loop, branch-region, and route-classification algorithms remain the
factual authority.

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
source fingerprint set. Every origin phase used to build the payload must declare the same
generation. Cross-generation composition is invalid.

## Evidence and derivation

Direct source evidence contains a stable evidence ID, relative source path, exact source span,
source text, line-basis/provenance fields when available, and origin references.

Every canonical node and edge has at least one of:

1. one or more direct source-evidence IDs; or
2. a deterministic derivation record containing its own stable ID, derivation kind, ordered input
   origin references, proof references, and a bounded explanation.

Derived proof kinds include existing M06 branch-arm membership, immediate post-dominator merge,
SCC/loop membership, call-site return continuation, terminal classification, and static
reachability. Proof records never claim more than their origin algorithms establish.

## Reachability decision table

Statuses are assigned conservatively and in this order:

| Evidence | Status |
|---|---|
| Item is itself unresolved or depends on an unresolved transfer | `unresolved_dynamic_behavior` |
| Reachable in the resolved static graph and guarded by a supported proven requirement | `conditionally_reachable` |
| Reachable in the resolved static graph and guarded only by possible/inferred requirements | `reachable_under_inferred_requirements` |
| Reachable in the resolved static graph without a known gate | `proven_reachable` |
| Not statically reachable and an unresolved dynamic transfer could reach it | `possibly_dead` |
| Not statically reachable and the resolved static graph is not closed for another reason | `unreachable_in_resolved_static_graph` |
| Not statically reachable, the supported graph is closed, and no unresolved transfer can reach it | `proven_unreachable` |

M10 does not prove arbitrary expression satisfiability. Unsupported Python, dynamic jumps, custom
screens, unknown registries, and unresolved dispatch prevent a closed-world unreachable claim.

## Serialization

Normalized canonical serialization is UTF-8 JSON with sorted keys, compact separators, finite
JSON values, and records sorted by stable ID. It includes schema version, source generation,
structural records, evidence references, origins, and reachability. It excludes timestamps,
durations, run IDs, transient errors, absolute output paths, and other operational metadata.

## Persistence states

Persisted phase and canonical records declare their source generation. Public analysis state is
one of `stale`, `current_partial`, `current_complete`, or `failed`. The last known-good canonical
payload remains available as `stale` until a replacement for the current generation is committed.
A failed later inspection projection cannot invalidate a current canonical payload.

## Suppression versus deletion

The canonical graph never deletes aliases, technical corridors, support-only terminals, or raw
branch members for presentation reasons. Simplified projection records may suppress or collapse
them, but must retain canonical member IDs and provide navigation to the underlying canonical
records and evidence.
