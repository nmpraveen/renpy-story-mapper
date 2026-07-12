# Browser API contract

The packaged browser is a presentation client for the loopback-only Python service. The service
owns story topology, evidence, organization state, session/CSRF enforcement, request bounds, and
path redaction. JavaScript never derives authoritative connectivity.

## Two-level M07 surface

The only visible levels are `route_map` and `detail_evidence`. Stations and line segments open the
same Detail/Evidence workspace directly. **Back to Route Map** is the sole level transition. Pan,
zoom, fit, search, filters, and follow-on pages alter visual position or density only.

The first page requests no more than 30 meaningful stations. Dense pages use an independent line
cursor: Next exhausts `edge_next_offset` slices for the current station page before advancing
`next_offset`, and Previous follows a bounded history of cursors actually visited. The client
rejects more than 30 stations, 180 line segments, or 240 combined rendered items. Status text
reports both station and line ranges plus overflow. Technical one-in/one-out work remains
line-corridor coverage and is not expanded into singleton cards.

## Locked M07 routes

- `POST /api/v1/m07/route-map` with `{offset, limit, edge_offset, edge_limit}`
- `POST /api/v1/m07/detail` with `{element_id}`
- `GET /api/v1/m07/organization`
- `POST /api/v1/m07/organization/prepare` with `{}`
- `POST /api/v1/m07/organization/start` with `{run_id, confirm_cloud: true, budgets}`
- `POST /api/v1/m07/organization/cancel` with `{}`
- `POST /api/v1/m07/assembly/apply` with `{assembly_id}`

Open, render, Detail/Evidence, and prepare never construct a provider. Cloud work begins only at
the explicit start mutation after confirmation. Organization state reports scope counts, calls,
tokens, AI coverage, technical coverage, and an ETA range; cancellation preserves validated
scopes. A partial assembly remains reviewable and requires an explicit apply mutation.

## Local shell routes

The existing bootstrap, opaque native picker, project create/open/refresh, deterministic analysis
progress/cancel, settings, diagnostics, shutdown, Host/Origin, session, CSRF, CSP, cache, and error
redaction boundaries remain unchanged. No browser request contains an absolute filesystem path.

`mock-api.js` mirrors the live method interface and exact mutation bodies. It is enabled only by
the explicit `?mock=1` acceptance URL. The M07 Chrome harness serves these production assets from
an ephemeral `127.0.0.1` origin and records zero remote requests and zero provider constructions.
