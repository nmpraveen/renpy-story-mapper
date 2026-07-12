# Browser API contract

The browser is a presentation client for the loopback-only Python service. `contract.js` is the
single frontend route manifest. All routes are under `/api/v1`; the server owns authentication,
CSRF, Host/Origin checks, request bounds, path redaction, and authoritative story data.

## Core rules

- Reads include `X-RSM-Session`; mutations also include `X-RSM-CSRF`.
- Native dialogs return `{selection: {id, kind, display_name}}`. `id` is an opaque, launch-scoped
  capability. No browser request or response needs an absolute filesystem path.
- Presentation responses own node IDs, parentage, order, kinds, edges, facts, and evidence. The
  frontend only lays out the returned bounded page.
- View requests send numeric levels `1` (arcs), `2` (events), and `3` (evidence), with limits of
  80 nodes and 120 edges. The client rejects more than 240 combined render items.
- `node_continuation.has_more` or `edge_continuation.has_more` must remain visible as bounded-slice
  overflow; the client never silently fetches an unbounded graph.
- Search, facts, and evidence are separate authoritative queries. Search text is never interpreted
  as a local graph query in production.
- Opening, rendering, searching, or loading evidence must not start organization. Organization
  start is a separate consent-bearing mutation, and apply/discard are explicit draft mutations.

## Routes

`GET /api/v1/state`, `GET /api/v1/tasks/current`, `POST /api/v1/dialog/source`,
`POST /api/v1/dialog/project/open`, `POST /api/v1/dialog/project/save`,
`POST /api/v1/projects/open`, `POST /api/v1/projects/create`,
`POST /api/v1/projects/refresh`, `POST /api/v1/tasks/cancel`,
`POST /api/v1/presentation/view`, `POST /api/v1/presentation/search`,
`POST /api/v1/presentation/evidence`, `POST /api/v1/presentation/facts`,
`GET /api/v1/organization`, `POST /api/v1/organization/start`,
`POST /api/v1/organization/drafts/apply`, and
`POST /api/v1/organization/drafts/discard`.

The optional state extensions used by the frontend are `recent_projects` and `settings`. The
optional local-only endpoints are `PUT /api/v1/settings` and `GET /api/v1/diagnostics`. If absent,
the UI retains in-browser view preferences and reports diagnostics as unavailable without exposing
paths. The integration owner should either implement these extensions or remove the optional
controls from the packaged shell.

## Mock contract

`mock-api.js` implements the same method-level interface with opaque selections and deterministic
fixtures. It is enabled only by the explicit `?mock=1` acceptance URL; production launch URLs do
not include that flag. The mock records every method call so acceptance can prove that project
opening and story traversal make zero implicit organization-start requests.
