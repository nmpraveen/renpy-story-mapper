# Phase 04 Track B/C rollup workflow seam

Status: Rejected preliminary scalar integration contract v1; superseded by v2

Version: `story-map-v2-rollup-workflow-v1` (historical)

The effective contract is
`docs/milestones/M15_PHASE_04/TRACK_C_ROLLUP_WORKFLOW_SEAM_V2.md`. This preliminary version is
preserved because its assumption that exact derived child/request identities exist at Prepare was
rejected after C1 completed the dependency analysis.

This seam extends Track B's provider-neutral workflow without importing C1 semantic types. It
freezes the provider-call taxonomy and preview ceilings needed for C1's predetermined section and
whole-game rollup slots. It does not change reader contract v2 or define browser routes.

## Call kinds and ceilings

Add two canonical `ProviderCallKind` values:

- `section_rollup`
- `whole_game_rollup`

Add two finite nonnegative preview ceiling fields:

- `section_rollup_calls`
- `whole_game_rollup_calls`

Each field is the maximum provider calls authorized across the unchanged run for its kind,
excluding separately approved job-specific indeterminate retries. A rollup slot may make at most
one initial cloud call. Invalid/refused output uses deterministic fallback and consumes no repair
or loopback call. There is no replacement review for either rollup kind.

`section_rollup_calls` must cover every non-cached eligible section slot. It is zero when all
section slots are structurally resolved or exactly cache-eligible. `whole_game_rollup_calls` covers
every non-cached fixed-membership consecutive reduction slot plus the final overview slot. A
deterministic fallback slot consumes zero provider calls. The existing
`indeterminate_retry_calls` is a global maximum across mapping and rollup kinds; every retry still
requires exact job-specific approval.

## Ordered rollup descriptors

Rollups are a separately frozen ordered descriptor list attached to the same exact workflow plan
and one approval. They are not silently encoded as mapping `WorkflowJobDescriptor` records.
Track B may name the scalar record `WorkflowRollupDescriptor`; it contains:

- `plan_id`
- `authority_identity`
- `job_id`
- `rollup_id`
- `call_kind`: exactly `section_rollup` or `whole_game_rollup`
- `stage`: exactly `section`, `reduction`, or `overview`
- `ordinal`: zero-based unique stable order within the plan
- `corridor_id`: required for `section`, null otherwise
- `route_id`: nullable exact route owner
- `parent_rollup_id`: required for `reduction`/`overview` except the single root overview, null for
  section slots
- `ordered_child_ids`: nonempty exact existing event IDs for `section`, or exact accepted
  section/rollup IDs for `reduction`/`overview`
- `membership_identity`: digest of stage, corridor/route ownership, and ordered child IDs
- `prompt_version`
- `schema_version`
- `adapter_version`
- `critical`: true when the slot contains a choice, route, rejoin, ending, or new branch

IDs are opaque. The descriptor list is built from the prepared fixed membership plan, persisted,
and reused; no assembly-time replanning or dynamic provider splitting is allowed. A materialized
attempt additionally binds exact serialized request bytes and the existing provider-input/cache
identity fields. Generated prose may affect those bytes but cannot change the descriptor's frozen
membership, order, route owner, stage, or ceiling.

## Attempt lifecycle and provider identity

Both rollup kinds use the existing Track B claim/lease, durable reservation, cancellation,
accounting, cache, crash recovery, `indeterminate`, and explicit job-specific retry rules. Status
and HTTP responses identify an indeterminate rollup by exact `job_id`, `attempt_id`, and call kind.
An indeterminate rollup never auto-resubmits. A cancelled run remains terminal.

The only provider identity is the approved cloud policy: `codex-cli`, `gpt-5.6-terra`, High
reasoning, fast mode off. Rollups have no loopback mode. Cache identity binds exact serialized
request bytes, the descriptor membership identity, prompt/schema/adapter versions, provider,
model, reasoning, fast mode, and cloud mode; run routing is excluded.

The `section` stage proposes prose plus contiguous first/last existing-event references inside one
deterministic corridor. `reduction` and `overview` stages receive only already verified fixed-order
child summaries. Python proves membership/order/route ownership after every result. Any invalid,
refused, or exhausted slot falls back deterministically without a repair loop.
