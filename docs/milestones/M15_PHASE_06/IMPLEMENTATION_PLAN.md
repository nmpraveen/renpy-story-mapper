# M15.2 Phase 06 - Story River implementation plan

Updated: 2026-08-01

Status: focused browser proof ready for user acceptance

## Outcome and boundary

Replace the family-tree presentation with a vertically unbounded HTML Story River. The shared story
flows down a neutral main stream; choices and conditions create locally colored tributaries; and an
automatic panel explains the route currently selected or passing through the reading position.

Phase 05 is the accepted factual and language baseline. Preserve its event order, branch ownership,
conditions, state provenance, route flow, destinations, rejoins, loops, endings, search, human names,
and technical evidence. Phase 06 changes frontend composition only: no API, persistence, Python graph,
AI pass, or source-game change.

## 1. Frontend route context

Build one internal route context for every rendered arm from its existing `selection_id`:

- root sibling codes use `A` through `Z`, then `AA`, `AB`, and so on;
- nested siblings append an ordinal to their parent code, such as `B.1` and `B.2`;
- each context records parent code, fork origin, caption, control kind, outcome kind, depth, target,
  state provenance, and one of eight accessible local palette slots;
- palette slots restart at each fork, may repeat after eight arms, and never replace the visible code;
- nested routes use their own local slot while retaining parent lineage; and
- cross-label `route_flow` inherits its owning arm context until a proven rejoin, ending, unresolved
  target, or loop reference.

Expose this context only as DOM data and CSS custom properties. Keep semantic decision, condition,
rejoin, ending, and unresolved markers independent of route color.

## 2. Story River composition

- Render the shared story as an ordinary top-to-bottom DOM document with no canvas bounds.
- Keep event stations on a neutral main stream.
- Render two-to-four immediate arm headers as a local tributary fan; stack five or more as colored
  elbows. Connectors are local decorative CSS or SVG and require no global geometry measurement.
- Place owned prose, nested choices, and cross-label route events in full-width colored route sections
  below the immediate headers rather than permanent narrow lanes.
- Keep sections with at most two descendant items open; collapse longer sections behind a concise
  route-colored summary.
- Group sibling arms with the same proven rejoin target into one confluence labelled
  `The story comes back together`, linked to the existing target selection ID. Keep differing targets,
  endings, unresolved destinations, and loop references separate.
- Suppress a repeated arm-level rejoin sentence only when the visible confluence carries the same
  fact. Preserve approximately `68ch` story prose and secondary Python/source detail.

## 3. Automatic route panel

Add a dedicated progressive-reader panel, separate from the legacy witness-path panel. It shows:

- route swatch and code, or `Main story`;
- current route/event title and originating fork;
- whether the player chose or the game checked;
- concise continuation, rejoin, ending, unresolved, or loop status and target; and
- up to three existing path-compatible state-provenance links.

Click and focus update it immediately. The existing throttled reading-position function selects the
nearest visible route or main-story event as scrolling proceeds. Search results, chapter links,
destination/rejoin links, and provenance backlinks reveal their target, focus it, and synchronize the
panel. At wide desktop widths the panel is a sticky third column; at intermediate widths it is a
compact sticky bar; at narrower existing desktop widths it returns to document flow.

## 4. Proof, parallel work, and gate

The coordinator owns route-context logic, renderer integration, panel behavior, milestone files, and
the final browser proof. After the DOM contract is frozen, one visible `gpt-5.6-sol` Ultra task owns
Story River CSS/palette/breakpoints and another owns focused tests only. Their edits must not change
Python structure, contracts, or story wording.

Focused validation covers route codes, nested lineage, 2/3/5/7/9-arm forks, color persistence,
immediate and delayed rejoins, differing targets, ending, unresolved and loop states, keyboard labels,
panel synchronization, search and story links, and horizontal overflow. The first rendered gate is the
fitting-room cross-label route plus one immediate rejoin and one nested decision at 1920px and 1280px.

Stop after presenting that proof. Whole-game regeneration, broad CI, packaging, Release, review, and
PR work wait for explicit user acceptance.

## Mock-fidelity correction

The first implementation passed its structural checks but was rejected visually on 2026-07-31. It
treated the existing family tree as the base and added route color; the selected mock instead makes
the river itself the dominant organizing object.

The correction therefore changes the focused presentation contract:

- the shared chronology is a thick, continuous dark river behind compact centered event cards;
- two-to-four immediate choices leave it as broad colored tributaries carrying compact route cards;
- proven siblings visibly flow into one strong merge capsule and then back into the dark river;
- descendant route sections are closed initially and only the selected arm's owned continuation
  opens, so nested decisions do not dominate the default timeline; and
- the route panel keeps the working synchronization behavior but adopts the mock's quieter current
  path, outcome synopsis, and return-to-story hierarchy.

Two new visible `gpt-5.6-sol` Ultra tasks own the CSS reset and mock-fidelity tests. The coordinator
owns the compact focus behavior, panel composition, integration, and new browser proof. The rejected
screenshots remain comparison evidence only. Whole-game regeneration and broad validation are still
gated on acceptance of the corrected focused proof.

The implementation, focused static checks, and focused 1920px/1280px real-game browser proof are
complete. The user-acceptance gate remains open. Do not apply or regenerate the whole game until the
user accepts the focused proof.
