# Browser API contract

The browser is a presentation client for the loopback-only Python service. `contract.js` is the
single frontend route manifest. All routes are under `/api/v1`; the server owns authentication,
CSRF, Host/Origin checks, request bounds, path redaction, and authoritative story data.

## Core rules

- Reads include `X-RSM-Session`; mutations also include `X-RSM-CSRF`.
- Native dialogs return `{selection_id, kind, display_name}`. `selection_id` is an opaque,
  launch-scoped
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

`GET /api/v1/bootstrap`, `GET /api/v1/recent`, `POST /api/v1/native-picker`,
`POST /api/v1/projects/open`, `POST /api/v1/projects/create`,
`POST /api/v1/projects/refresh`, `GET /api/v1/analysis/progress`,
`POST /api/v1/analysis/cancel`, `POST /api/v1/story/view`,
`POST /api/v1/story/search`, `POST /api/v1/story/evidence`,
`POST /api/v1/story/facts`, `GET /api/v1/organization/draft`,
`POST /api/v1/organization/consent`, `POST /api/v1/organization/review`,
`POST /api/v1/organization/apply`, `POST /api/v1/organization/discard`, and
`POST /api/v1/shutdown`.

The bootstrap response includes `recent_projects`, `settings`, and the server's route manifest.
`PUT /api/v1/settings` and `GET /api/v1/diagnostics` complete the local view-state and troubleshooting
flows. Session and CSRF values are injected into the empty packaged meta elements when the index is
served; they are never stored in the asset bundle.
The shutdown mutation is acknowledged before the launcher exits, so Quit does not leave the local
server running in the background.

Every story-view node includes the backend-owned `unresolved` boolean. The frontend unresolved
toggle filters only this field and never infers classification from kind text or opaque payloads.

The draft envelope contains pending `drafts`, each draft's raw candidate at `draft.candidate.arcs`
and `draft.candidate.events`, and persisted decisions at `reviews[draft_id]`. Review mutations send
exactly `{draft_id, target_kind, target_id, decision}`. Arc member counts use `event_ids`; event
member counts use `beat_ids`. Candidate rows are paged 40 at a time and Apply remains disabled
until every candidate across all pages has an explicit persisted approved/rejected decision.

## Mock contract

`mock-api.js` implements the same method-level interface with opaque selections and deterministic
fixtures. It is enabled only by the explicit `?mock=1` acceptance URL; production launch URLs do
not include that flag. The mock records every method call so acceptance can prove that project
opening and story traversal make zero implicit organization-start requests.
