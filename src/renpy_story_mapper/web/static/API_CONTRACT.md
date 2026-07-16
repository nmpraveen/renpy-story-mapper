# Browser API contract

The packaged browser is a presentation client for the loopback-only Python service. The service
owns topology, evidence, organization state, request bounds, and path redaction. JavaScript never
derives authoritative connectivity.

## M10 deterministic inspection

For an M10 project, the browser chooses the best deterministic result in this order: current
simplified M10 inspection, current canonical M10 graph, a coherent stale simplified/canonical
pair, then the M07 Technical Structure. An applied M08 AI Story Map remains selectable but does
not override the normal M10 default.

- `POST /api/v1/m10/inspection-map` accepts only
  `{view, offset?, limit?, edge_offset?, edge_limit?, query?, focus?}`. `view` is `simplified` or
  `canonical`; node and edge limits are at most 30 and 180. `query` is at most 256 characters and
  `focus` is at most 512 characters.
- `POST /api/v1/m10/detail` accepts exactly `{view, element_id}`. `element_id` is at most 512
  characters and may identify a visible node or edge, canonical region, fact, evidence record, or
  deterministic proof.

Canonical inspection is independent of the optional simplified projection. Before inspection is
served, the service validates analysis-state schema 2 and its canonical generation/hash binding.
Before a simplified response is served, it also validates the projection schema, source
generation, and `canonical_graph_hash` against the selected canonical payload. A mismatch returns a typed
`status: "unavailable"` response with `view`, a bounded reason, and `generation_status`; stale and
current generations are never composed. Canonical inspection remains available when a current
canonical graph exists but simplified projection creation failed.

Available pages expose `status: "available"`, `level: "route_map"`, `view`, source and authority
identities, generation status, bounded node and incident-edge slices, lanes, coverage, and paging.
`generation_status` includes freshness, analysis status, canonical/simplified availability,
last-known-good status, completed phases with nonnegative durations, and a sanitized failure
record with failed-phase duration when present. Available
details use `level: "detail_evidence"` and remain bounded to 60 records per related collection.

Whole-graph search is server-side over canonical authority regardless of the selected view and
does not expand the rendering boundary. It can match an
exact canonical ID, underlying graph-node ID, label, visible title/caption, source text, relative
source path and line, and condition/effect metadata. Results include matched record ID/kind,
canonical ID, target view, bounded offsets, canonical page target, and the visible simplified
representative when one exists. A suppressed match without a representative switches to canonical
inspection and opens that exact record; a represented match centers its simplified node. `focus`
performs exact focus resolution for canonical IDs and graph-node IDs. At most 50 search matches are
materialized. M10 does not invent day,
chapter, numbered-name, or asset-name heuristics when deterministic metadata is absent.

Detail links expose regions, facts, evidence, and proofs without deriving new topology. Branch
region detail includes classification, split, ordered arms, arm entry and member count,
merge/rejoin when present, persistence reasons, unresolved/terminal summaries, attached gate and
effect facts, origins, proof records, and canonical escape IDs. Loop, terminal, call-return, and
reachability records expose their existing deterministic origins/proofs. Route-to-target solving
is not an M10 endpoint.

After a failed create or refresh, the browser requests retained deterministic results and enters
the workspace when any ordered fallback is available. It keeps a persistent failure banner with
the failed phase, freshness, completed phases, and last-known-good status. A failure before the
first canonical payload produces a bounded partial-analysis/diagnostics state instead of an empty
invented map. Opaque creator code is displayed as
`Unsupported creator Python · preserved, not executed`; it is not executed or automatically
reclassified as an unresolved transfer.

## M08 AI Story Map

After an exact current-generation assembly is applied, the browser can display the AI Story Map
when selected. M10 deterministic inspection remains the normal default, and Technical Structure
remains a comparison and fallback view with unchanged deterministic authority.
The projected boxes are real AI event groups and the projected connections are the deterministic
quotient edges; the browser never renames technical nodes one by one or invents connectivity.

- `POST /api/v1/m08/ai-story-map` accepts only
  `{node_offset, node_limit, edge_offset, edge_limit, edge_cursor?}`. Limits are 30 nodes and 180
  edges. `edge_offset` is scoped to the exact node slice, not the global projected edge list. The
  initial incident-edge page uses offset zero with no cursor; every nonzero offset requires the
  deterministic `edge_cursor` returned for that exact projection, node slice, edge offset, and
  limit. Mismatched, stale, or tampered cursor/offset combinations are rejected.
- `POST /api/v1/m08/ai-story-detail` accepts only `element_id` plus optional bounded technical and
  evidence cursors. Limits are 30 member nodes, 180 member edges, and 60 evidence records.
- `POST /api/v1/m08/comparison` retains the four numeric page fields and returns the initial
  incident-complete AI page plus the independently paged Technical Structure under one exact
  `authority_hash` with `authority_unchanged: true`. Its numeric `edge_offset` applies to Technical
  Structure only; subsequent AI incident pages use the direct AI endpoint's bound cursor.

An available AI page contains only projected edges incident to at least one returned node, in the
projection's stable order. `next_edge_cursor` exhausts that bounded incident set before
`next_node_offset` becomes available. `continuation_endpoints` identifies the real off-page source
or target for every crossing edge; the edge itself retains all deterministic roles, gates, effects,
evidence, merge, loop, and ending truth. No response invents topology or exceeds 30 nodes and 180
edges.

Missing, stale, or invalid applied organization returns an explicit unavailable reason and a safe
Technical Structure fallback reference. It never returns a project path, source root, provider
object, or credential. Detail/Evidence contains member technical nodes and edges, exact gates and
effects, reviewer corrections and pins, evidence-backed claims, and relative qualified source
locations. Opening, switching, paging, comparing, replaying, and reopening are provider-free.

## Two-level M07 surface

The only visible levels are `route_map` and `detail_evidence`. Stations, line segments, and
continuation portals open the same Detail/Evidence workspace. **Back to Route Map** is the sole
level transition. Pan, zoom, fit, search, filters, and paging do not create semantic levels.

The first page requests at most 30 stations. Dense pages use an independent line cursor: Next
exhausts `edge_next_offset` before `next_offset`; Previous follows bounded cursor history. The
client rejects more than 30 stations, 180 edges, or 240 combined items.

Lane IDs are opaque deterministic strings. The client consumes `lanes: [{id, kind}]` and never
maps them to a fixed row count. An edge with one endpoint outside the station slice remains visible
as a labelled continuation portal; the client neither invents the endpoint nor drops the edge.

## Locked M07 routes

- `POST /api/v1/m07/route-map` with `{offset, limit, edge_offset, edge_limit}`
- `POST /api/v1/m07/detail` with `{element_id}`
- `POST /api/v1/m07/bounded-window/resolve` with exactly one selector:
  `{node_ids}` or `{entry_node_id, exit_node_id}`. The provider-free response is exactly
  `{window, selection_request}`. `window` is the complete content-addressed
  `BoundedNarrativeWindow`; `selection_request` contains the selector plus the complete expected
  IDs and hashes required by prepare.
- `GET /api/v1/m07/organization`
- `POST /api/v1/m07/organization/prepare` with
  `{scope_ids, window_requests, soft_seconds, hard_seconds, soft_tokens, hard_tokens, hard_calls}`.
  At least one explicit `scope_id` or exact resolver `selection_request` is required. There are at
  most 64 combined work units; nested window IDs and objects are bounded by the domain limits.
  Every supplied budget is a positive integer. Defaults are `soft_seconds: 600`, `hard_seconds: 900`,
  `soft_tokens: 1500000`, `hard_tokens: 2000000`, and `hard_calls: 48`.
- `POST /api/v1/m07/organization/start` with
  `{run_id, confirm_cloud: true, scope_ids, window_ids, selection_hash, authority_hash,
  recovered_source_acknowledgement, model, budgets}` copied exactly from prepare. `model` is
  exactly `{id: "gpt-5.6-luna", reasoning: "high", fast_mode: false}` and `budgets` has exactly the
  five finite budget fields.
- `POST /api/v1/m07/organization/cancel` with `{}`
- `POST /api/v1/m07/assembly/apply` with `{assembly_id}`
- `POST /api/v1/m07/assembly/discard` with `{assembly_id}`

The superseded `/api/v1/organization/*` consent, draft, review, apply, and discard endpoints are
not part of the browser API and return `404`. Cloud work can begin only through the provider-free
prepare response followed by the exact nine-field, single-use start binding above.

Resolve and prepare do not construct a provider. Empty, global/full-map, unknown, duplicate,
disconnected, oversize, extra-field, and stale window selections fail closed. Start validates all
nine fields against the fresh, single-use prepared binding and revalidates current route authority
and recovered-source coverage before cloud work can begin. No start field is inferred or refreshed
after consent. The browser polls organization status until a terminal status is actually returned.

Prepare returns exactly `run_id`, `scopes`, `scope_ids`, `window_ids`, `windows`,
`selected_counts`, `cached`, `validated`, `model`, `budgets`, `authority_hash`, `selection_hash`,
`recovered_source_acknowledgement`, `source_coverage`, and `requires_confirm_cloud`. Counts cover
selected work units, deterministic scopes, windows, nodes, internal edges, boundary nodes and
edges, evidence, and facts. Organization status exposes the same consent summary under
`scope_ids`, `window_ids`, `selected_counts`, `cached`, `validated`, `model`, `budgets`,
`selection_hash`, `prepared_authority_hash`, and `recovered_source_acknowledgement`; its existing
`authority_hash` remains the current authoritative route hash.

Every organization response labels its top-level status provenance as `current_run` or
`project_history` and also exposes the full persisted generation state under the explicitly
labelled `project_history` object. Current-run scope totals, statuses, validated/fallback/pending
counts, coverage, partial state, and cache reuse are filtered to the exact prepared `scope_ids` and
`window_ids`; disjoint checkpoints from the same route generation cannot enter those values.
`accounting` reports current in-memory progress plus the incremental persisted-attempt delta while
that run identity is known. After opening or reopening a project, it instead labels cumulative
calls, tokens, attempts, cache hits, and summed provider-attempt time as persisted project history.
The flat accounting fields mirror that same labelled provenance, so historical attempts are never
presented as one run or as a zero-call replay.

## Review and route search

The current draft is returned as `organization.assembly.items`. Candidate results expose their
claims, evidence links, reviewer corrections, and pins. Candidates remain proposals and never
replace the technical map before Apply.

Apply persists the selected draft. Discard persistently supersedes the current draft and returns
organization status; the browser then refreshes status before reporting success.

Bounded route-search results are exposed as
`global_search: {query, element_ids, next_after}` and are consumed without expanding the current
render boundary. Global navigation can supply `global_navigation.next: {offset, edge_offset}`.
Local filtering and ordinary paging remain available when no global result is active.

## M12 route-to-target panel

Bootstrap advertises the three local M12 paths under `routes.m12` as exactly `destinations`,
`solve`, and `result`. The browser validates that each is a versioned local API path before using
it. No route endpoint is inferred from a selected element.

- Destinations accepts `{offset, limit}` or `{query, offset, limit}` and returns bounded nodes as
  `{kind, target_id, title, subtitle}`.
- Solve accepts exactly `{destination_kind, target_id}`. A cache hit returns
  `{cached: true, request_identity, result}`. A new solve returns
  `{cached: false, request_identity, analysis}` and uses the existing analysis progress and cancel
  lifecycle.
- Result accepts exactly `{request_identity}` and returns the normalized deterministic route.

The panel is part of `route_map`; it is not another semantic level. It shows one recommended
route, bounded alternatives, the four approved user badges, deterministic instructions, separated
assumptions/scenes/choices/repeats/requirements/effects/commitments/warnings, and expandable
technical evidence. JSON export recursively sorts object keys and exports only the normalized
result. Selection changes mark an existing result stale; cancellation and failure do not replace
that result. Detail traversal reuses the existing Detail/Evidence workspace and canonical escape.

## M13 optional Narrative overlay

The Narrative toggle overlays validated M13 titles and summaries on the deterministic M11 Scenes
view. Turning it off restores the unchanged M11 presentation. The job drawer and narrative claims
remain inside `route_map` and `detail_evidence`; they do not create a third semantic level. Claim
labels distinguish factual claims, AI interpretation, and review suggestions. Citations are
resolved lazily through the persisted claim DAG only after a user opens them.

- `POST /api/v1/m13/snapshot` accepts only `{offset?, limit?}` with at most 200 current-authority
  job summaries. It reports scene coverage, job states, stale/unavailable counts, and M12 coverage.
- `POST /api/v1/m13/artifact` accepts exactly `{artifact_id}` and returns at most 256 validated
  claim summaries plus publication and coverage warnings.
- `POST /api/v1/m13/citations` accepts exactly `{claim_id}` and lazily resolves at most 256 claims
  and 60 direct M10/M11/M12 authority records.
- `POST /api/v1/m13/prepare` accepts one exact model, privacy mode, M12 toggle, selected scene
  scope, hard limits, and deterministic transport-batch limits. It performs provider-free sizing
  of the complete hierarchy and returns a disabled `m13-run-preparation-v1` manifest with provider
  and requested/resolved model identity, logical-job and estimated-call counts, input/output token
  estimates, cost confidence, selected scope, and all limits. Cost is visibly unavailable when the
  adapter cannot estimate it reliably; no cost limit may then be implied.
- `POST /api/v1/m13/start` accepts exactly `{preparation_id, confirm_cloud:true}`. The preparation
  ID binds that single confirmation to the manifest shown in the browser. No missing, stale, false,
  or provider-unavailable confirmation starts a run.
- `POST /api/v1/m13/status` and `POST /api/v1/m13/cancel` accept `{}`. Status distinguishes prepared,
  running, cancelling, succeeded, partial, failed, cancelled, and hard-limit outcomes. Cancellation
  reaches the active provider and preserves every independently validated artifact. Retrying prepares
  a new exact consent manifest; accepted cache entries replay without provider calls, so only missing
  or failed jobs remain provider work.

Cloud AI is disabled by default. These read endpoints are provider-free and never transmit story
material. Unknown, stale, corrupt, foreign-owner, or oversized records fail closed. Browser
rendering never changes M10, M11, or M12 authority and never treats mutually exclusive routes as
one chronology. The run drawer keeps deterministic views useful with Narrative disabled and displays
provider/model, scope, fact-only or story-text mode, M12 inclusion, estimated calls and tokens, cost
availability, and call/token/time/concurrency limits before the one manifest-bound confirmation.

## Local shell and acceptance

Bootstrap, opaque native pickers, project create/open/refresh, analysis progress/cancel, settings,
diagnostics, shutdown, Host/Origin, session, CSRF, CSP, cache, and error-redaction boundaries remain
unchanged. No browser request contains an absolute filesystem path.

Production startup always constructs `LocalApi`; URL parameters cannot enable a mock project. The
Chrome harness serves the packaged assets through `LocalWebServer` and `ProjectApi` against a
temporary SQLite project on ephemeral `127.0.0.1`. Its provider factory raises on construction,
and its network log rejects every non-loopback request.
