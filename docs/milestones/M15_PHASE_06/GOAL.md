# M15.2 Phase 06 - Story River reader

Status: focused browser proof ready for user acceptance

## User outcome

Read a Ren'Py game as one vertically unbounded story river. The shared story runs top to bottom;
choices and conditions create clearly colored local routes; persistent routes keep their identity
until a proven rejoin, ending, loop, or unresolved destination; and the reader always shows which
route is currently in view.

## First proof

Before applying the design to the complete game, prove the Story River presentation on real sections
that contain:

- the fitting-room split where `Keep arguing with her` owns a cross-label continuation and
  `Push her out` bypasses it;
- a simple fork whose arms immediately rejoin; and
- a nested decision inside one owning route.

The proof is useful when route identity and color remain clear, the correct paths visibly return to
the shared river, expanded story prose stays readable, navigation links still work, and there is no
horizontal page overflow at 1920px or 1280px desktop widths.

## Smallest implementation

- Derive frontend-only route contexts from existing arm selection IDs and Python-owned outcomes.
- Replace the family-tree fork styling with a shared river, local tributaries, full-width route
  sections, and explicit confluences.
- Add one automatic selected-route panel synchronized by click, focus, scrolling, search, and story
  navigation.
- Keep immediate routes visible, open short descendants, and collapse longer route sections.
- Preserve existing story text, state backlinks, destination/rejoin links, source evidence, search,
  event order, and structural counts.

The implementation sequence and internal presentation contract are in
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

## Exclusions

- No pan, zoom, global node coordinates, giant graph canvas, minimap, route filter, or view toggle.
- No Python graph, HTTP API, database, saved-project schema, AI wording, or source-game changes.
- No mobile optimization, packaging, Release, broad CI, PR preparation, or whole-game regeneration
  before the focused rendered proof is accepted.

## Acceptance checks

1. Every visible arm has a stable route code and a non-color route label.
2. Route color persists through owned nested and cross-label events, then stops at the proven
   confluence or terminal state.
3. Two-to-four-arm forks read as local tributaries; five-or-more-arm forks stack without squeezing
   prose.
4. Immediate shared targets render once as `The story comes back together`; different targets stay
   separate.
5. The selected-route panel reports the current route, origin, decision/condition ownership,
   outcome, target, and available earlier-state links.
6. Click, focus, scroll, search, index, destination, rejoin, and provenance navigation keep the panel
   synchronized.
7. The focused real proof has correct branch ownership, nesting, rejoins, and zero horizontal page
   overflow at 1920px and 1280px.

## Rejected first visual attempt

The first focused build preserved the correct route facts and interactions, but the user rejected its
presentation on 2026-07-31. It remained a wide family tree with thin connectors, colored borders, and
large nested route boxes; it did not resemble the selected Story River mock closely enough.

The replacement proof must use the mock's visual hierarchy: one thick dark central river, compact
centered event stations, broad colored tributaries, compact route cards sitting on those streams, a
strong shared merge capsule, and generous whitespace. Deep owned routes start collapsed and reveal
on route selection instead of filling the page by default. The rejected screenshot remains under
[`output/m15-phase06-story-river-proof-20260731`](../../../output/m15-phase06-story-river-proof-20260731)
only as comparison evidence; it is not an accepted proof.

## Rejected second visual attempt

The 2026-07-31 replacement kept the correct route facts but drew its flow with CSS pseudo-elements:
rectangles, thick borders, and `clip-path` polygons. The user rejected it on 2026-08-01 because the
tributaries read as stiff straight bars rather than water. A clipped rectangle cannot curve, taper,
or flare, so no amount of CSS tuning could reach the mock.

The accepted approach paints flow instead of bordering it. `web/static/river.js` measures each
event's laid-out boxes and fills one SVG layer per event containing the trunk, its mouth flare at a
split, the bezier tributaries out to each arm card, the merge back into the confluence, the tapered
tails of routes that end, and the stream into an owned route. Long carries run down an edge lane so
a rejoin never drags a band across another route's opened story. Colour and every card, chip, and
type decision stay in CSS; only geometry moved.

The renderer, panel, route-focus behavior, painter, and CSS are integrated and pass the focused
contract. The 2026-08-01 real-game browser proof confirms Route B ownership across the fitting-room
event, B.1/B.2 nesting, confluence and provenance navigation, panel synchronization, and zero
horizontal page overflow at 1920px and 1280px, in light and dark themes. Evidence is under
[`output/m15-phase06-story-river-proof-20260801`](../../../output/m15-phase06-story-river-proof-20260801).

The user accepted this presentation on 2026-08-01, which closes the visual gate that the two
rejected attempts left open.
