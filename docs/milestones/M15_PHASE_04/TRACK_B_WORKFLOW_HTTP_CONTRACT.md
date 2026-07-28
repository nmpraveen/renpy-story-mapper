# Phase 04 Track B workflow HTTP contract

Status: Frozen integration contract v1

Contract/version: `story-map-v2-workflow-http-v1`

Machine-readable schema:
`src/renpy_story_mapper/story_map_v2/schemas/story_map_workflow_http_v1.schema.json`

Public synthetic fixture:
`tests/fixtures/story_map_v2/phase04_workflow_http_v1.json`

This is the separately versioned browser mutation/status seam for Track B's existing durable Story
Map V2 workflow. It does not redefine Track C's reader contract and does not authorize browser code
to call `StoryMapWorkflowService` directly. The contract is provider-neutral: source authority,
provider request bytes, and workflow construction remain server-owned.

## Bootstrap advertisement and routes

The browser may use workflow controls only when the bootstrap response actually contains the exact
object `routes.story_map_v2_workflow`. Absence of that object means every workflow control remains
unavailable. Track D must not infer routes, probe paths, or reuse `routes.story_map_v2`, which is the
independently versioned Track C reader route object.

When advertised, `routes.story_map_v2_workflow` contains `contract` plus these six route keys and
paths. Every route accepts local HTTP `POST` only:

| Key | Path |
|---|---|
| `prepare` | `/api/v1/story-map-v2/workflow/prepare` |
| `start` | `/api/v1/story-map-v2/workflow/start` |
| `cancel` | `/api/v1/story-map-v2/workflow/cancel` |
| `resume` | `/api/v1/story-map-v2/workflow/resume` |
| `retry` | `/api/v1/story-map-v2/workflow/retry` |
| `status` | `/api/v1/story-map-v2/workflow/status` |

This contract freezes only the advertised shape. A later Track B implementation owns adding it to
bootstrap; this contract-only commit does not advertise or implement any route.

## Requests

Requests have exactly the following keys and no others:

- `prepare`: `{contract}`. The current open project and Track A plan/authority are server-owned;
  the server allocates `run_id`.
- `status`: `{contract, run_id}`.
- `start`, `cancel`, and `resume`: `{contract, run_id, preview_identity}`. `start` atomically
  creates approval for that exact preview and starts background execution; there is no separate
  approve route.
- `retry`:
  `{contract, run_id, preview_identity, job_id, indeterminate_attempt_id}`.

The browser never supplies a plan, authority payload, provider or model setting, resource ceiling,
privacy scope, source material, serialized request identity, prompt, provider request bytes, or
provider response bytes. Unknown keys fail as `invalid_workflow_request` before service dispatch.

## Successful response

Every successful command returns exactly:

`{contract, command, preview, approval, status, retry_approval}`

`command` is one of `prepare`, `start`, `cancel`, `resume`, `retry`, or `status`.
`preview`, `approval`, and `status` are authoritative projections for the selected run in every
success response. `retry_approval` is non-null only for a successful `retry` command and is `null`
for the other six commands.

### Preview

The preview projects the existing frozen `WorkflowPreview` without transmitting request material:

- `run_id`, `preview_identity`, `plan_id`, and `authority_identity`;
- ordered `jobs`, each exactly `{job_id, scope_id, chunk_id, critical}`;
- `derived_semantic_plan`, the provider-neutral
  `story-map-v2-derived-semantic-workflow-v2` descriptor frozen at
  `db50539a8616bb29b6735b95a60ff401ce0f10d2`;
- `cache_hits` exactly `{cloud_job_ids, loopback_job_ids}`;
- `policy` exactly
  `{policy_version, prompt_version, schema_version, cloud, loopback,
  allow_refusal_fallback, section_synthesis, rollup_synthesis}`;
- each non-null provider setting exactly
  `{provider, model, reasoning, fast_mode, mode, adapter_version}`;
- each derived semantic policy setting exactly
  `{prompt_version, schema_version, provider, model, reasoning, fast_mode, mode,
  adapter_version}` and cloud-only Terra/High/fast-off;
- `ceilings` exactly
  `{mapping_calls, review_calls, fallback_calls, section_synthesis_calls,
  route_reduction_calls, route_summary_calls, whole_game_reduction_calls,
  final_overview_calls, rollup_synthesis_calls, input_tokens, output_tokens, elapsed_ms,
  submission_slots, indeterminate_retry_calls}`; `submission_slots` is exactly six; and
- `privacy` exactly the six booleans `cloud_story_content`, `loopback_story_content`,
  `durable_raw_requests`, `durable_raw_responses`, `durable_provider_diagnostics`, and
  `durable_absolute_paths`. The four durable-sensitive flags are always `false`.

The cloud setting is the frozen workflow policy (`codex-cli`, `gpt-5.6-terra`, `high`, fast mode
`false`, mode `cloud`). A configured loopback setting uses mode `loopback`. A null loopback setting
requires `allow_refusal_fallback` and `loopback_story_content` to be false; a non-null loopback
setting requires both to be true. Cloud and loopback cache-hit job lists remain separate.

### Approval, status, and retry approval

`approval` is always exactly
`{state, approval_identity, preview_identity, plan_id, authority_identity}`. `state` is
`not_approved` or `approved`. All four identity fields are null when not approved and non-null when
approved.

`status` is exactly:

- `run_id`, `preview_identity`, `approved`, and `cancelled`;
- non-negative `pending_jobs`, `active_jobs`, `accepted_jobs`, `structural_fallback_jobs`,
  `resumable_jobs`, and `indeterminate_jobs`;
- finite non-negative `accounting` fields `calls`, `input_tokens`, `output_tokens`, and
  `elapsed_ms`;
- authoritative booleans `can_approve`, `can_start`, `can_cancel`, and `can_resume`; and
- ordered `indeterminate_retries`. Each entry is exactly
  `{job_id, attempt_id, call_kind, approval_state, retry_approval_identity,
  can_approve_retry}`. `call_kind` is `mapping`, `replacement_review`, `refusal_fallback`,
  `section_synthesis`, or `rollup_synthesis`; `approval_state` is `required` or `approved`. An
  approved entry has a non-null retry approval identity and cannot be approved again.

Cancellation is irreversible and terminal for the selected run. After cancellation is persisted,
no later job may start, `can_resume` is false, and a `resume` command fails with
`workflow_command_conflict`. Only interrupted, non-cancelled work can resume. A separately prepared
new run may reuse immutable cache entries; it does not revive the cancelled run.

A successful retry approval is exactly
`{retry_approval_identity, preview_identity, job_id, indeterminate_attempt_id}`. It authorizes only
that exact latest job/attempt lineage under the unchanged preview and remains one-use.

## Stale authority and approval

A stale workflow command returns HTTP 409 with exactly:

`{contract, error: {code, message, sanitized_reason, current_run_id,
current_preview_identity}}`

`code` is exactly `stale_workflow_preview` or `stale_workflow_approval`. `message` is a nonempty
sanitized browser message. `sanitized_reason` is only one of `preview_replaced`,
`authority_changed`, `plan_changed`, `provider_policy_changed`, `ceilings_changed`,
`privacy_scope_changed`, or `cache_state_changed`. The two current identities are either both
non-null for the replacement preview or both null when no replacement preview exists.

Changed authority, plan, provider policy, ceilings, privacy scope, or cache state never carries an
approval forward. A fresh `prepare` allocates a new `run_id` and preview identity; `start` must
atomically create approval for that exact new preview before background execution begins.

## Other errors

Non-stale failures return exactly `{contract, error: {code, message, sanitized_reason}}`, with no
partial preview/status data. The frozen code, HTTP status, and reason pairs are:

| HTTP | `code` | `sanitized_reason` |
|---:|---|---|
| 400 | `invalid_workflow_request` | `invalid_request` |
| 404 | `workflow_run_not_found` | `run_not_found` |
| 409 | `workflow_command_conflict` | `command_not_available` |
| 413 | `workflow_request_too_large` | `request_too_large` |
| 500 | `workflow_internal_error` | `internal_error` |
| 503 | `workflow_unavailable` | `service_unavailable` |

Messages are nonempty, bounded, static or allowlisted prose. No error contains raw provider data,
source text, request/response bytes, stderr, credentials, exception representations, or absolute
paths.

## Ownership and compatibility

- Track B owns this frozen contract plus domain/protocol support for detailed status and exact
  retry identities, the two scalar derived semantic call kinds, component ceilings, and the
  provider-neutral derived plan descriptor. Track B does not edit Project API or browser
  composition in this slice.
- Track A supplies only the frozen plan and authority through its stable seam. Track B does not
  import planner types or recompute occurrence/chunk authority in this browser boundary.
- Track C2 owns future `ProjectApi`/dispatch/bootstrap/error transport composition from this exact
  schema and fixture. Track C's reader contract v2 and reader routes remain byte-for-byte unchanged
  and separately versioned.
- Track D consumes only advertised routes and the envelopes above. It never invokes
  `StoryMapWorkflowService` directly and performs no workflow-authority inference.
- This contract task includes no UI wiring, server implementation, provider construction, or
  provider call. Its fixture is public, synthetic, and contains no private source or machine path.

## Derived semantic workflow v2

The preview's `derived_semantic_plan` is separate from and does not mutate the ordered mapping
`jobs`. It contains exactly `semantic_plan_identity`, `story_chunk_plan_identity`,
`authority_identity`, ordered `corridors`, `route_memberships`, `fan_in`, and the six derived call
maxima. Each corridor is exactly `{corridor_id, route_owner, event_slot_upper_bound, ordinal}`.
Each persistent route membership is exactly `{route_id, ordered_corridor_ids}`. `fan_in` is 24.

Let `U_c` be a corridor's `event_slot_upper_bound`, `U_r` the sum for corridors in persistent route
`r`, `U_common` the sum for corridors with null route owner, `R` the number of nonempty persistent
route memberships, and `F = 24`. Define:

```text
reduce(n) = 0                                  when n <= F
reduce(n) = ceil(n / F) + reduce(ceil(n / F)) when n > F
```

The exact frozen maxima are:

- `section_synthesis_calls`: number of nonempty corridors;
- `route_reduction_calls`: sum of `reduce(U_r)` across persistent routes;
- `route_summary_calls`: `R`;
- `whole_game_reduction_calls`: `reduce(U_common + R)`;
- `final_overview_calls`: one when `U_common + R > 0`, otherwise zero; and
- `rollup_synthesis_calls`: sum of the preceding four rollup fields, excluding section synthesis.

Later `section_synthesis` and `rollup_synthesis` jobs are registered immutably only when their
children have published. They bind the semantic plan, candidate generation, job ID, call kind,
rollup node role (`route_reduction`, `route_summary`, `whole_game_reduction`, or
`final_overview`), nullable corridor/route ownership, exact ordered child IDs and normalized prose
hashes, ordinal, serialized request identity, and cloud provider identity. Those derived bytes and
children are deliberately absent from Prepare because they do not exist yet.

Component and total ceilings are enforced transactionally. Both derived call kinds use only the
approved `codex-cli`/`gpt-5.6-terra`/High/fast-off cloud policy. They permit no replacement review,
loopback, repair, adaptive split, or automatic resubmission. Invalid or refused output receives
deterministic zero-call fallback. Durable lease, cache, accounting, cancellation, definite
nontransmission, indeterminate, and exact job-specific retry rules remain shared with mapping.
