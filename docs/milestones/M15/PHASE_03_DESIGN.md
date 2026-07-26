# M15.1 Phase 03 shared design

Status: Frozen for track dispatch

Baseline: `e81523fe2cc42f1bc3d8dcb1a839bfd28876dfe9`

This note freezes the smallest cross-track seams. It is subordinate to `GOAL.md`,
`docs/MASTER_PLAN.md`, and the Phase 03 handoff.

## One product flow

```text
stored accepted Phase 02 core
  -> optional one-call validated synthesis
  -> deterministic section/event/choice projection
  -> read-only Story Map V2 local API
  -> normal-flow story page
  -> M12 witness and existing Detail/Evidence/source navigation
```

There is no new event boundary algorithm, hierarchy compiler, repair loop, topology model, or
provider lifecycle. Synthesis is optional decoration over immutable existing anchors.

## Identity envelope

One current project record binds:

- `schema = story-map-v2-project-v1`
- exact accepted core schema and canonical SHA-256
- Phase 02 `source_identity`
- current source generation and canonical authority hash carried by the accepted core/package
- all source paths that make the generic payload dependency invalidation authoritative
- import timestamp only as non-identity metadata

Zero or one synthesis record binds:

- `schema = story-map-v2-synthesis-record-v1`
- the project/core identity above
- synthesis request payload hash, prompt version, response-schema identity
- requested and resolved provider identity, reasoning, fast mode, call count, and token/time data
- validated synthesis content or one sanitized failure state

Any identity mismatch makes the stored synthesis unavailable. The deterministic core view remains
available when synthesis is absent or stale. Reopen reads these records and does not construct or
invoke a provider.

## Synthesis request and response

The request contains only:

- ordered event anchor ID, title, summary, characters, and source-order ordinal;
- ordered branch-outcome anchor ID and summary;
- compact choice/arm captions, conditions, effects, destinations, and rejoin facts needed to
  understand consequences;
- instructions restricting every returned ID to the supplied event anchor IDs.

It excludes raw script, source paths when anchors suffice, canonical node IDs not needed by the
model, private oracle/reference answers, old provider responses, screenshots, secrets, unrelated
files, and game assets.

The versioned response has exact root fields:

- `story_title`
- `story_overview`
- `ordered_sections[]` with `section_title`, `section_summary`, and ordered
  `event_anchor_ids[]`
- `optional_threads[]` with `title`, `summary`, and ordered `event_anchor_ids[]`

Validation rejects unknown/foreign IDs, duplicates, empty sections, reverse chronology, duplicate
keys, and malformed text. A structurally valid response may omit accepted events; Python inserts
each omitted event once into the nearest chronological section and exposes one analysis note.
Successful synthesis must finish with five to seven non-empty chronological sections. Any invalid,
unavailable, refused, timed-out, transport-failed, or identity-failed result selects the complete
deterministic fallback and spends no additional call.

## Story projection

The read model has:

- story title, overview, synthesis/fallback status, and collapsed analysis notes;
- ordered broad sections;
- each accepted event exactly once with its existing anchor, story text, characters,
  reachability, warnings, selection target, Detail/Evidence target, and source locator;
- choices placed at their accepted story location;
- arms in exact Python order with caption, condition, effects, destination, rejoin, reachability,
  warnings, selection target, Detail/Evidence target, and source locator;
- nested choices only below the parent arm named by exact `parent_lineage`;
- one compact continuation after a proven local rejoin.

Section IDs are presentation-only and never become route targets. The line-793 Day 2 boundary
uses its deterministic destination/rejoin target and does not invent an event anchor.

### Frozen continuation selection seam

Each arm keeps its existing `rejoin_node_id` and `rejoin_line` fields and adds exactly one
`rejoin_binding` field. It is `null` when no local rejoin is proven or the current project
authority cannot resolve that rejoin uniquely. Otherwise it uses the existing `NavigationBinding`
serialized shape:

```json
{
  "selection_id": "story-map-v2-continuation:<sha256>",
  "destination_kind": "generic_scene",
  "target_id": "<existing M12 target id>",
  "detail_kind": "story_map_v2_continuation",
  "detail_id": "story-map-v2-continuation:<sha256>",
  "source": {
    "relative_path": "<current-core relative path>",
    "start_line": 793,
    "end_line": 793
  }
}
```

The binding contains one of the six destination kinds accepted by `M12RouteService`; it is never
`canonical_node`. The server derives the opaque ID as the lowercase hex SHA-256 of canonical
compact UTF-8 JSON for
`["story_map_v2_continuation_v1", relative_path, rejoin_node_id, rejoin_line]`, prefixed by
`story-map-v2-continuation:`. Equal proven local rejoins therefore deduplicate by ID. The path and
detail endpoints recompute the ID from the current stored core, optionally resolve its binding
from current project authority, and reject forged or stale IDs. The browser consumes this object,
never creates one, and renders at most one compact continuation for each ID in a local branch
context. It is an action/selection target, not another story event. The generalized integration fixture is
`tests/fixtures/story_map_v2_phase03_continuation_contract.json`.

## Read-only API

Bootstrap exposes one `story_map_v2` route group:

- `map`: returns the complete bounded story projection for the open project;
- `path`: accepts exactly one visible event/arm/deterministic-boundary selection ID and returns a
  compact M12-backed witness projection or an honest unresolved result;
- `detail`: accepts the same selection ID and returns/redirects to the exact existing
  Detail/Evidence and qualified source-navigation targets.

The API never accepts synthesis prose, mechanics, topology, source paths, or provider settings
from the browser. Missing/stale V2 records return a bounded unavailable response without falling
back to historical Stage H/E.

## Path projection

Each selectable item carries an exact Python-built binding:

- visible selection ID (existing Phase 02 anchor where one exists);
- destination kind and target ID accepted by `M12RouteService`;
- event/choice/arm source locator and evidence/detail identity;
- optional deterministic rejoin/boundary binding.

Track C calls the current `M12RouteService` and projects only its recommended known witness:
important visible choices, requirements, effects, scene titles, and uncertainty in story order.
If the solver has no proven complete route, the panel shows the known static prefix and one short
plain-language explanation. It never upgrades unresolved or incomplete results.

## Browser contract

- Story Map V2 is the primary route page after an open project has a current V2 record.
- Use a bounded readable column and semantic normal-flow HTML; no world canvas.
- Broad sections are primary cards; events and local choices are nested content.
- Arms stack vertically at narrow widths and 200% zoom.
- Requirements/effects are short badges; exact source remains secondary Detail/Evidence content.
- Technical warnings are behind one `Analysis notes` disclosure.
- Selection and keyboard focus are visible. Opening/closing detail preserves selected ID and
  scroll context. A small path panel and return-to-selected action do not create a third level.
- Only `route_map` and `detail_evidence` remain user-visible semantic levels.
- All assets are local; no remote font, script, style, image, analytics, or network dependency.

## Track ownership

- Track A owns Phase 03 typed contracts, synthesis/schema/validation/fallback, minimal persistence,
  base story projection, read-only map API, and generalized tests.
- Track B owns static HTML/CSS/JS/API-client/contract rendering and responsive browser tests. It
  consumes Track A response shapes without changing Python authority.
- Track C owns anchor-to-M12/detail/source bindings, path/detail endpoints, compact witness
  projection, and generalized navigation tests. It does not edit Track B static assets except an
  explicitly coordinated integration patch.
- The coordinator alone integrates, performs the private call, runs private acceptance, captures
  screenshots, updates lifecycle authority, pushes, and changes PR state.

Every track preserves Phase 02 mapper behavior, M10/M11/M12 semantics, historical code, and private
artifacts.
