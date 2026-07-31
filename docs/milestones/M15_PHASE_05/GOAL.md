# M15.1 Phase 05 - Progressive state-aware story timeline

Status: accepted functional baseline; superseded by Phase 06 Story River presentation

## User outcome

Give the app a Ren'Py game folder or script and read its story as a clean, full-width desktop
timeline. Linear story, choices, conditions, state-dependent routes, important effects, rejoins, and
endings must be understandable while scrolling.

## Done condition

Starting from the game's entry label, Python progressively builds the real execution and state flow;
AI summarizes those Python-owned corridors; and the existing desktop reader shows a coherent
whole-game timeline with correct branch membership, nesting, state back-links, destinations, and
rejoins.

The detailed implementation sequence is
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md). It is the active roadmap for the five remaining
reader corrections; this goal remains the concise product contract.

## First proof

Before full-game work, rebuild the Terrance section from its actual labels and jumps:

- show only its genuine menus and every arm;
- keep `Keep going / Take things to the next level` nested under `Say No`;
- follow `Do nothing` into the storage-room continuation;
- show the common continuation into the Lois story;
- use human destination and rejoin names;
- show relevant state effects without combining mutually exclusive outcomes; and
- contain no Gene/Faye choices or false ending.

The user accepted this rendered proof on 2026-07-28. The same progressive method can now be applied
to the full game.

The first rendered proof exposed three concrete product failures: the outline stacked large
technical cards without a clear branch tree, long story corridors were reduced to vague
consequences such as "the encounter escalates," and direct sibling routes did not read as a visible
fork. The corrected proof must preserve the same mechanics while restoring the actual story and its
family-tree relationships.

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
- The initial view is a compact top-to-bottom family tree. A control sits above its direct sibling
  routes, which fork horizontally; downstream controls remain beneath the exact route that owns
  them and receive enough width to remain readable.
- Semantic box roles are restrained and consistent: blue decisions, amber conditions, green story
  continuations, purple links or rejoins, neutral unresolved routes, and red only for a true ending.
- Colors are assigned from Python-owned graph facts, never inferred from dramatic prose.
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
2. The compact initial outline shows the Terrance family tree without horizontal page overflow or
   squeezed story text.
3. Every substantial captured corridor, including the storage-room continuation, has concrete
   expandable story detail at the correct place in the tree.
4. Technical evidence is available on demand but absent from the default reading surface.
5. Proven Lois continuations render as purple rejoins or links, while only true branch endings are
   red.
6. The rendered Terrance section is understandable by scrolling and is accepted by the user.
7. The full-game walker covers every reachable label or marks it unresolved without using AI chunks
   as story boundaries.
8. The first 10 AI summaries are useful before the remainder is parallelized.
9. The final desktop timeline preserves Python-owned branches, conditions, state provenance,
   destinations, rejoins, loops, and endings.
10. Cross-label events remain beneath the exact route that reaches them; shared continuations render
    once and loops use references rather than duplicated recursive story.
11. Default story headings, route captions, destinations, and rejoins use story language; raw Python
    remains in secondary detail.
12. State-dependent routes link to compatible earlier choices or assignments, or explicitly say that
    provenance is unresolved.
13. Closed descendant routes hide their content, and selected-arm detail uses the route width without
    horizontal overflow.
14. Completed stories do not show dead generation chrome, ordinary buttons do not misuse
    `aria-selected`, and duplicate recent projects are distinguishable.

## Exclusions

- No repair of the rejected 34-section chunk-owned grouping as the final architecture.
- No arbitrary event/group count.
- No mobile UI, zoom modes, giant graph canvas, packaging, Release, broad CI, PR preparation, or
  production hardening before story acceptance.
- No privacy/consent workflow or mandatory local/cloud fallback system.

## Handoff

The Terrance acceptance gate, graph-backed whole-game structure coverage, deterministic 597-packet
narrative projection, and cloud-AI summaries for all 597 packets are complete. All summaries passed
fidelity review; 594 story corridors are attached exactly once under their Python-owned label,
control arm, or continuation after three technical-only packets are excluded. The review project
renders 111 label events and retains all 324 story controls and 700 arms: 260 controls and 571 arms
remain in the default family-tree flow, while 64 startup, developer, and hint controls stay in
secondary detail. The 1920px browser inspection found no page or story-scroller horizontal overflow,
content-sized sibling routes, concrete expandable prose, and distinct semantic colors. A focused
coordinator correction replaced all structure-only fallback copy with proven next-state facts and
turned 29 labels without shared corridor prose into neutral control-derived gates; no parent event
borrows a child route summary. Phase 05 remains active for the five reader corrections below and
user acceptance of the assembled whole-game reader.

The five 2026-07-30 reader corrections are now implemented. Cross-label events remain beneath their
owning arms; 79 accepted stable-ID story names leave no machine-facing or fallback names; state,
destination, and rejoin links navigate to stable targets; closed descendants and route-wide detail
behave correctly; and completed-story chrome, ARIA, and recent-project presentation are corrected.
The final disposable review project preserves all structural counts and passes the focused 1920px
browser checks. On 2026-07-31 the user accepted this as the functional baseline and moved the remaining
story-flow navigation work into M15.2 Phase 06.
