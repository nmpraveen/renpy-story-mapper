# Ren'Py Story Mapper master plan

Updated: 2026-08-03

## Product goal

Build a quick desktop tool that accepts a Ren'Py game folder or readable script and produces a
clean, trustworthy, full-width scrolling story timeline. A reader should understand the linear
story, choices, conditions, nested routes, important state changes, destinations, rejoins, loops,
endings, and uncertainty without reading raw code.

This is a personal script/game-to-story checker. It is not a production workflow platform, hosted
service, universal Python interpreter, game editor, mobile app, or replacement Ren'Py runtime.

## Current decision

The selected direction is hybrid:

1. deterministic Python builds and freezes factual execution/state structure;
2. execution-derived corridors define story units;
3. AI titles and summarizes only those frozen corridors;
4. a simple scrolling reader presents the combined result; and
5. independent structure and browser audits verify the real artifact.

The existing Story River remains the last accepted integrated application baseline on Ms. Denvers.
It is not the current proof strategy for a new game. The Resort v0.2.2 hybrid Story Atlas is the
reference architecture proof, but it used a game already studied during diagnosis and does not
prove third-game generalization.

See [the complete history](PROJECT_HISTORY.md), [current state](PROJECT_STATE.md), and
[hybrid architecture](HYBRID_APPROACH.md).

## Story authority

Python owns:

- entry and execution order from labels, fallthrough, jumps, calls, returns, and known targets;
- menus, conditions, every arm, nested ownership, and conditional visibility;
- effects, requirements, state provenance, and path compatibility;
- exact corridor membership and source spans;
- destinations, rejoins, loops, local terminals, release terminals, and unresolved behavior;
- stable IDs, scope/reachability, and evidence.

AI may:

- title and summarize frozen corridors;
- explain character, motive, development, and route consequences;
- provide uncertainty notes; and
- editorially group adjacent corridors without moving or changing them.

AI may not invent or relocate mechanics. Unsupported dynamic behavior remains unresolved.

## Story-building model

```text
entry label
  -> readable linear corridor
  -> menu or condition
     -> exact branch-owned corridors
     -> nested choice or later state gate
     -> proven rejoin, persistent continuation, loop, ending, or unresolved target
```

When a later condition reads state established earlier, preserve both relationships:

- the visible split occurs where the condition is evaluated; and
- a dependency link points to the earlier choice or assignment that can establish it.

Source files, AI requests, token limits, model context windows, and arbitrary group counts are
transport details. They never define story events.

## Input and execution policy

- Original supplied game inputs are read-only.
- Trusted games may be executed when useful, preferably through a disposable headless copy.
- Generated and recovered files stay outside the original game directory.
- Game scripts and story content may be sent to cloud AI.
- Cloud AI is the default unless the user requests local processing.
- Supplied archives, extracted source trees, generated outputs, and model transcripts stay out of
  Git.

## Presentation boundary

The supported product outcome is a full-width desktop scrolling timeline:

- shared chronology reads top to bottom;
- choices and conditions fork locally;
- descendants remain beneath the exact route that owns them;
- immediate flavor routes can rejoin compactly;
- persistent routes remain separate until a proven rejoin or terminal;
- important state causes and later requirements are linked;
- story names are human-readable while raw Python remains secondary evidence;
- unresolved behavior is visible but not dominant; and
- long scrolling remains readable with no horizontal page overflow.

Do not make pan, zoom, fit, semantic zoom, mobile layouts, a giant world graph, or a production
dashboard part of the current plan.

## What the repository has already proved

- Safe read-only RPA/source ingestion and inert static parsing.
- Durable graph/state/evidence projects and incremental refresh.
- Canonical control, guard, state, rejoin, loop, and terminal facts.
- Human scene, route, and source-evidence projections.
- Optional editorial AI that cannot change deterministic authority.
- A complete accepted family-tree reader and painted Story River on Ms. Denvers.
- A source-grounded direct-analysis benchmark on Resort.
- A generic fix for Resort's cyclic region-parent failure.
- A complete hybrid Resort Atlas with 1,103 exact-once corridors and passing independent structure
  and Chrome audits.

## What remains unproved

- The existing integrated Story River app has not completed end to end on Resort.
- The old durable Story Map publication path still needs a broad Episode 3 nested-lineage canary.
- The hybrid architecture has not run on a genuinely unseen third game.
- The best reusable presentation after that proof is undecided.
- Static analysis cannot resolve every screen, timer, replay, persistent/platform, or opaque-Python
  mechanic.

## Current roadmap

The active contract is
[M16 Hybrid story mapping and third-game proof](milestones/M16_HYBRID_STORY_ATLAS/GOAL.md).

### Gate 1 - Third-game deterministic section

Run the unchanged extractor on a third unseen game. Prove one representative real section with
correct branch membership, nesting, conditions, state provenance, destinations, rejoins, loops or
terminals, and source evidence. Preserve any generic failure before repairing it.

### Gate 2 - Frozen corridors and editorial canary

Build execution-derived packets. Prove exact statement accounting, then inspect the first ten plus
difficult structural corridors. Correct packet shape or prompt before any bulk work.

### Gate 3 - Rendered prototype

Render one real section in Chrome. Check nested interaction, evidence, state/destination/rejoin
links, search/filter behavior, readability, console, long scrolling, and overflow. Stop if the
presentation is not useful.

### Gate 4 - Full audited result

Parallelize only editorial summaries. Integrate by stable ID with exact-once checks. Run independent
source/structure and rendered-browser audits. Record time to first useful story, full audited result,
manual interventions, model settings, and unresolved coverage.

### Gate 5 - Product selection

Only after the third-game proof, choose the smallest reusable surface:

- a static Story Atlas;
- a text-first dossier with deterministic evidence; or
- an adapted Story River using the same frozen hybrid packets.

Then implement only the seams demonstrated necessary by the proof.

## Delivery discipline

- Prove one real section before whole-game work.
- Run focused checks while changing parser/story/UI seams.
- Keep a failed baseline immutable and give repaired runs new identities.
- Do not repeat a failed bulk-summary pattern.
- Distinguish deterministic completion, AI completion, publication, and rendered acceptance.
- Use pull requests for GitHub updates.
- Do not let sunk cost or attractive screenshots substitute for cross-game correctness.

## Completion

The project succeeds when a new Ren'Py game can be turned into a coherent, source-grounded,
auditable scrolling story in reasonable time without a game-specific product rewrite. Branches,
state causes, routes, rejoins, endings, and uncertainty must be understandable to the user and
mechanically traceable to Python-owned evidence.
