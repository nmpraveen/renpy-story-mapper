# Ren'Py Story Mapper master plan

Updated: 2026-07-31

## Product goal

Build a desktop tool that accepts a Ren'Py game folder or script and produces a clean, readable,
full-width scrolling story timeline. The user should understand the story simply by scrolling,
including its choices, conditions, routes, important state changes, rejoins, and endings.

This is a quick personal story checker, not a production platform, game editor, universal Python
interpreter, mobile application, or public hosted service.

## Story-building model

The product builds the story progressively in execution order:

```text
entry label
  -> linear story corridor
  -> menu or condition
     -> branch corridors carrying their conditions and state
     -> later rejoin, route continuation, loop, or ending
```

When a later condition reads state established earlier, the map keeps both relationships:

- the visible branch starts at the later condition; and
- a dependency link points back to the earlier choice or assignment that enabled it.

Source-file boundaries, AI context windows, token limits, and arbitrary event counts are transport or
storage details. They never define story events.

## Python and AI responsibilities

Python owns:

- execution order from labels, jumps, calls, returns, and fallthrough;
- menus, arms, nested choice lineage, and conditions;
- direct assignments, increments, important state, and state provenance;
- branch destinations, demonstrated rejoins, loops, terminals, unresolved behavior, and source lines;
- exact membership of every story corridor and choice.

AI may:

- title and summarize linear corridors;
- explain characters, motives, developments, and branch consequences;
- editorially group adjacent Python-built corridors for reading; and
- check an assembled result as `PASS`, `PARTIAL`, `LOW`, or `FAIL`.

AI may not invent or relocate mechanics. Cloud AI is the default. Use a local LLM only when the user
explicitly requests local processing. Game and script content may be sent to cloud AI.

For bulk cloud summaries, the coordinator processes and inspects the first 10 items. After that
canary is useful, the remaining work is divided approximately evenly across three or four
user-visible `gpt-5.6-sol` High Codex tasks unless the user selects different settings. In this
project, "Codex task" or "Codex thread" always means an app-created task visible in the sidebar, not
an internal subagent.

## Input and execution policy

- Original game inputs are read-only.
- Trusted games may be executed when useful.
- Prefer a disposable copy and headless Ren'Py execution so the game does not open visibly.
- Generated or recovered files stay outside the original game directory.
- There is no privacy boundary between local and cloud story processing for this project.

## Desktop interface

The supported interface is a full-width desktop scrolling timeline on the user's current screen.

Required presentation:

- linear story reads top to bottom;
- choices expand locally into clearly nested branches;
- flavor choices that immediately rejoin remain compact;
- persistent routes remain visibly separate until they rejoin or end;
- later state gates show readable back-links such as `Requires: trusted Trevor earlier`;
- destinations and rejoins use human story names, not canonical node IDs;
- important state changes are visible without overwhelming the story; and
- source detail remains available as secondary evidence.

Not supported or required:

- pan or zoom;
- fit-to-screen or semantic zoom;
- special 100% or 200% modes;
- mobile layouts or mobile optimization;
- a giant world graph; or
- arbitrary limits such as 12-30 groups.

## Current foundation and correction

The existing parser, recovered Ren'Py source, control-flow facts, state facts, browser reader, and
source evidence are reusable. The previously published 34-section outline is rejected as product
evidence: it misplaced choices, dropped branch arms, flattened nesting, mislabeled endings, and hid
destinations. Its 103 AI summaries and 105 chunks may be diagnostic context, but they are not story
event authority.

M15.1 Phase 05 is the accepted functional baseline: it replaced chunk-owned presentation with the
progressive execution/state story walker described above. M15.2 Phase 06 now replaces only the
family-tree composition with a Story River reader.

## Current delivery roadmap

The Terrance proof, full-game deterministic walk, 597-corridor summary pass, and first whole-game
desktop checkpoint are complete. The active Phase 05 correction now proceeds in this order:

1. Compose cross-label events beneath the exact branch that reaches them, proving the contract on the
   real fitting-room route before regenerating the whole game.
2. Replace machine-derived condition, arm, destination, and rejoin wording with human story language,
   while retaining raw Python as secondary evidence.
3. Link later state gates, destinations, and rejoins to their earlier or downstream story points.
4. Fix collapsed descendant behavior and let selected-arm prose use the full route width.
5. Hide dead completed-story workflow chrome and correct ARIA/recent-project presentation defects.
6. Regenerate a disposable whole-game review project and obtain user acceptance of the rendered
   desktop timeline.

The detailed implementation contract, gates, and focused checks are in
[`docs/milestones/M15_PHASE_05/IMPLEMENTATION_PLAN.md`](milestones/M15_PHASE_05/IMPLEMENTATION_PLAN.md).

All five Phase 05 correction areas are implemented as of 2026-07-31. The final disposable review project
preserves the Python-owned counts, contains no machine-facing story names, and has working search,
state backlinks, destination/rejoin navigation, route-wide detail, completed-story chrome, and valid
ARIA at 1920x1080. The user accepted it as the factual and language baseline.

The active M15.2 Phase 06 roadmap is:

1. Derive stable frontend-only route contexts and local route colors from existing arm facts.
2. Render a vertically unbounded main river with local tributaries, full-width owned route sections,
   explicit confluences, and no pan or zoom.
3. Synchronize an automatic selected-route panel with scrolling and existing story navigation.
4. Prove the presentation on the real fitting-room route, one immediate rejoin, and one nested choice
   at 1920px and 1280px before applying it to the whole game.

The first implementation of steps 1-4 was rejected visually on 2026-07-31 because it remained a
colored family tree rather than matching the selected Story River mock. The focused redesign now
targets a thick dark main river, broad colored tributaries, compact station cards, an unmistakable
merge, and selection-opened deep routes. Whole-game work still waits for acceptance of that proof.

The active contract is
[`docs/milestones/M15_PHASE_06/GOAL.md`](milestones/M15_PHASE_06/GOAL.md), with detailed sequencing in
[`docs/milestones/M15_PHASE_06/IMPLEMENTATION_PLAN.md`](milestones/M15_PHASE_06/IMPLEMENTATION_PLAN.md).

Run focused tests during implementation. Broad CI, Release, packaging, PR work, and general polish
wait until the user accepts the story or explicitly asks to ship it.

## Completion

The product is successful when the user can give it a game or script and scroll through a coherent
whole-story timeline where branches, route requirements, state causes, outcomes, rejoins, and endings
are understandable without reading raw code.
