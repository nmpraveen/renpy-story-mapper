# Browser API contract

The packaged browser is a presentation client for the loopback-only Python service. The service
owns topology, evidence, organization state, request bounds, and path redaction. JavaScript never
derives authoritative connectivity.

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
- `GET /api/v1/m07/organization`
- `POST /api/v1/m07/organization/prepare` with
  `{scope_ids, soft_seconds, hard_seconds, soft_tokens, hard_tokens, hard_calls}`; every budget is
  a positive integer. Defaults are `soft_seconds: 600`, `hard_seconds: 900`,
  `soft_tokens: 1500000`, `hard_tokens: 2000000`, and `hard_calls: 48`.
- `POST /api/v1/m07/organization/start` with
  `{run_id, confirm_cloud: true, scope_ids, budgets}` copied exactly from prepare
- `POST /api/v1/m07/organization/cancel` with `{}`
- `POST /api/v1/m07/assembly/apply` with `{assembly_id}`
- `POST /api/v1/m07/assembly/discard` with `{assembly_id}`

Prepare does not construct a provider. Start validates that `scope_ids` and `budgets` exactly match
the fresh, single-use prepared binding before cloud work can begin. The browser polls organization
status until a terminal status is actually returned.

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
