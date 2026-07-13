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

Open, render, detail, and prepare never construct a provider. Cloud work begins only after the
confirmed start mutation. The browser polls organization status until a terminal status is
actually returned. Candidate content never replaces the technical map before apply.

## Optional review and global-navigation extensions

The browser safely consumes these fields when present:

- Detail: `ai_candidates: [{id, title, summary, claims, correction?, pinned?}]`; each claim is
  `{id, text, evidence_ids}` and references records in detail `evidence`.
- Organization: `candidates` or `assembly.items`, carrying claims, corrections, and pins.
- Route page: `global_navigation.next: {offset, edge_offset}` and
  `global_search: {query, element_ids}`. Local filtering remains available when absent.

The current backend does not expose candidate contents, corrections, or pins in Detail/status and
has no discard mutation. Persisted discard needs an authenticated endpoint such as
`POST /api/v1/m07/assembly/discard` with `{assembly_id}`, returning normal organization status with
`status: "discarded"`. Global search needs `{query, after, limit}` →
`{query, element_ids, next_after}`; global navigation needs an addressable cursor for an element
ID. Until then, Discard closes local review and explicitly reports that the project is unchanged.

The current start dispatcher binds authority and scopes server-side through the single-use
`run_id`, but does not validate the echoed `scope_ids` or `budgets`. It must reject a start whose
echo differs from the prepared binding. The client already sends the echo and fails closed when
prepare omits a non-empty `scope_ids` array or any finite requested budget.

## Local shell and acceptance

Bootstrap, opaque native pickers, project create/open/refresh, analysis progress/cancel, settings,
diagnostics, shutdown, Host/Origin, session, CSRF, CSP, cache, and error-redaction boundaries remain
unchanged. No browser request contains an absolute filesystem path.

Production startup always constructs `LocalApi`; URL parameters cannot enable a mock project. The
Chrome harness serves the packaged assets through `LocalWebServer` and `ProjectApi` against a
temporary SQLite project on ephemeral `127.0.0.1`. Its provider factory raises on construction,
and its network log rejects every non-loopback request.
