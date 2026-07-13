# Browser API contract

The packaged browser is a presentation client for the loopback-only Python service. The service
owns topology, evidence, organization state, request bounds, and path redaction. JavaScript never
derives authoritative connectivity.

## M08 AI Story Map

After an exact current-generation assembly is applied, the browser defaults to the AI Story Map.
Technical Structure remains a comparison and fallback view with unchanged deterministic authority.
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

## Local shell and acceptance

Bootstrap, opaque native pickers, project create/open/refresh, analysis progress/cancel, settings,
diagnostics, shutdown, Host/Origin, session, CSRF, CSP, cache, and error-redaction boundaries remain
unchanged. No browser request contains an absolute filesystem path.

Production startup always constructs `LocalApi`; URL parameters cannot enable a mock project. The
Chrome harness serves the packaged assets through `LocalWebServer` and `ProjectApi` against a
temporary SQLite project on ephemeral `127.0.0.1`. Its provider factory raises on construction,
and its network log rejects every non-loopback request.
