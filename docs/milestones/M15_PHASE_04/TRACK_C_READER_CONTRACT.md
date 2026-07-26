# Phase 04 Track C/D reader contract

Status: Frozen integration contract v1

Schema/version: `story-map-v2-reader-contract-v1`

Machine-readable schema:
`src/renpy_story_mapper/story_map_v2/schemas/story_map_reader_contract_v1.schema.json`

Public synthetic fixture:
`tests/fixtures/story_map_v2/phase04_reader_contract_v1.json`

This is the small frozen seam between Track C's Python assembly/read APIs and Track D's browser.
It is additive to the accepted Phase 03 `map`, `path`, and `detail` endpoints. Python remains the
only authority for topology, mechanics, membership, ordering, route ownership, path witnesses,
selection location, cursor validity, revisions, and `NEW` state.

## Routes

All Phase 04 endpoints are local POST routes under `/api/v1/story-map-v2/`:

- `manifest`
- `status`
- `section-page`
- `branch-page`
- `locate`
- `search`
- `path-page`
- `detail-page`
- `view-state`
- `view-state/save`

The exact route strings and request fields are frozen in the public fixture. Track D must consume
the bootstrap-advertised route table and must not infer paths. Track C may add fields or endpoints
only in a later schema version; it may not change or reinterpret v1 fields.

## Revision and cursor rules

- Every successful read response includes the integer `map_revision`.
- The manifest and status select the current readable generation without a caller-supplied
  revision. Every other read binds the caller's `map_revision`.
- A stale revision returns HTTP 409 with exactly
  `{error: {code: "stale_map_revision", message}, map_revision}`. The returned revision is the
  currently readable revision; the response contains no partial requested data.
- Cursors are opaque nonempty strings. A cursor binds the schema version, map revision, endpoint,
  resource identity, stable order, offset, and effective limits. Tampered, foreign, or mismatched
  cursors fail closed as `invalid_cursor`; a cursor from an older revision returns
  `stale_map_revision`.
- The initial page omits `cursor`. A non-null `next_cursor` is replayed only with the same route,
  revision, resource identity, query/selection, and limits.

## Bounds and shells

- A section page contains at most 30 events, 240 rendered items, and 1 MiB serialized JSON.
- Branch, path, and detail pages contain at most 240 rendered items and 1 MiB serialized JSON.
- Search and locate operate over unloaded sections. A section need not be hydrated to locate or
  search one of its selections.
- Every valid nonempty section or branch page has at least one server-authored `shell`. A shell
  names an ordered subset of returned item IDs and carries the deterministic continuation/rejoin
  metadata needed by Track D. JavaScript may lay out shells but may not create membership.
- Path and detail pagination is a bounded projection of existing M12/Phase 03 navigation. It does
  not solve a new path, rebuild authority, or create another semantic level.
- `is_new` and `new_facts` are supplied by Python. Track D may hide their presentation with the
  persisted `hide_new` view-state flag but must not derive, add, or remove `NEW` facts.

## Compatibility and ownership

- Phase 03 single-core records remain readable through the existing Phase 03 endpoints. A Phase 03
  compatibility manifest may expose one synthetic section under this v1 reader without rewriting
  the stored Phase 03 record.
- Track C owns the schema implementation, cursor validation, status/manifest generation, pages,
  locate/search, paged path/detail, and view-state persistence.
- Track D owns only browser hydration, rendering, navigation, focus/selection restoration, and
  browser acceptance against this contract.
- Prepare/approval/cancel/retry mutations remain the frozen Track B workflow-service seam and are
  deliberately not redefined by this read contract. The status response reads its progress,
  cancellability, resumability, retry-approval, and indeterminate state; command routing must be
  coordinated separately by the Phase Coordinator rather than invented by either C or D.
- The fixture is synthetic and provider-free. It contains no private source, provider response,
  absolute path, credential, or machine-specific value.
