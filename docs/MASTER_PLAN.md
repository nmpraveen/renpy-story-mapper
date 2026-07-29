# Ren'Py Story Mapper master plan

Updated: 2026-07-28

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

The active correction is M15.1 Phase 05: replace chunk-owned presentation with the progressive
execution/state story walker described above.

## Delivery sequence

1. Build a deterministic progressive walk for the Terrance section.
2. Render its exact branch tree, state effects, destinations, and rejoin into the scrolling reader.
3. Add AI titles, summaries, and consequences after the structure is correct.
4. Let the user inspect that real section.
5. Once accepted, walk the full game.
6. Validate the first 10 bulk summaries, then parallelize the rest.
7. Show the complete desktop timeline and fix only concrete comprehension problems.

Run focused tests during implementation. Broad CI, Release, packaging, PR work, and general polish
wait until the user accepts the story or explicitly asks to ship it.

## Completion

The product is successful when the user can give it a game or script and scroll through a coherent
whole-story timeline where branches, route requirements, state causes, outcomes, rejoins, and endings
are understandable without reading raw code.
