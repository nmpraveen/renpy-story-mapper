# M15.1 Phase 05 - Progressive state-aware story timeline

Status: Corrected Terrance proof ready for user acceptance

## User outcome

Give the app a Ren'Py game folder or script and read its story as a clean, full-width desktop
timeline. Linear story, choices, conditions, state-dependent routes, important effects, rejoins, and
endings must be understandable while scrolling.

## Done condition

Starting from the game's entry label, Python progressively builds the real execution and state flow;
AI summarizes those Python-owned corridors; and the existing desktop reader shows a coherent
whole-game timeline with correct branch membership, nesting, state back-links, destinations, and
rejoins.

## First proof

Before full-game work, rebuild the Terrance section from its actual labels and jumps:

- show only its genuine menus and every arm;
- keep `Keep going / Take things to the next level` nested under `Say No`;
- follow `Do nothing` into the storage-room continuation;
- show the common continuation into the Lois story;
- use human destination and rejoin names;
- show relevant state effects without combining mutually exclusive outcomes; and
- contain no Gene/Faye choices or false ending.

The user inspects this rendered proof before the same method is applied to the full game.

The first rendered proof exposed two concrete product failures: the outline stacked large technical
cards without a clear branch tree, and long story corridors were reduced to vague consequences such
as "the encounter escalates." The corrected proof must preserve the same mechanics while restoring
the actual story.

## Implementation contract

- Python follows labels, fallthrough, jumps, calls, returns, menus, conditions, and direct state
  changes in execution order.
- Linear statements between control points become story corridors.
- Every branch carries its path condition and state provenance.
- A later condition links back to the earlier choices or assignments that can establish it.
- Routes merge only at demonstrated rejoins. Loops and unresolved dynamic behavior remain explicit.
- AI names and summarizes corridors after mechanics are frozen. AI does not own membership or edges.

## AI and execution

- Cloud AI is the default. Use a local LLM only when the user explicitly requests it.
- Game and script content may be sent to cloud AI.
- Trusted games may execute; prefer a disposable headless run.
- Original game inputs remain read-only.
- For full-game bulk summaries, inspect the first 10 results, then split the remainder approximately
  evenly across three or four user-visible `gpt-5.6-sol` High Codex tasks unless the user says
  otherwise. These are app-created sidebar tasks/threads, not internal subagents.

## Interface

- Full-width desktop scrolling timeline on the user's current screen.
- No pan, zoom, fit, semantic zoom, 100%/200% variants, or mobile optimization.
- The initial view is a compact top-to-bottom outline with a shared vertical trunk and clear fork
  connectors for sibling choices. Branches never compete in narrow side-by-side columns.
- Clicking an outline node expands a full-width story detail directly beneath it without losing the
  reader's place.
- Short summaries remain concrete. Expanded summaries state what actually happens in each captured
  corridor; placeholders such as "it escalates" or "the encounter continues" are not acceptable.
- Immediate rejoins appear once after their sibling arms. Persistent routes remain visibly separate
  until their demonstrated rejoin.
- State variables, reachability, source lines, and Detail/Evidence controls live in a separate
  secondary disclosure rather than the default story flow.

## Acceptance checks

1. The Terrance proof matches the script's menu nesting, route destinations, state effects, and
   Lois rejoin.
2. The compact initial outline shows the Terrance tree vertically without horizontal squeeze.
3. Every substantial captured corridor, including the storage-room continuation, has concrete
   expandable story detail at the correct place in the tree.
4. Technical evidence is available on demand but absent from the default reading surface.
5. The rendered Terrance section is understandable by scrolling and is accepted by the user.
6. The full-game walker covers every reachable label or marks it unresolved without using AI chunks
   as story boundaries.
7. The first 10 AI summaries are useful before the remainder is parallelized.
8. The final desktop timeline preserves Python-owned branches, conditions, state provenance,
   destinations, rejoins, loops, and endings.

## Exclusions

- No repair of the rejected 34-section chunk-owned grouping as the final architecture.
- No arbitrary event/group count.
- No mobile UI, zoom modes, giant graph canvas, packaging, Release, broad CI, PR preparation, or
  production hardening before story acceptance.
- No privacy/consent workflow or mandatory local/cloud fallback system.

## Handoff

Stop first at the rendered Terrance proof. After user acceptance, continue to the whole game and the
first-10 AI-summary canary.
