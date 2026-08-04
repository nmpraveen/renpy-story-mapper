# M16 - Hybrid story mapping and third-game proof

Status: active direction; Resort proof complete; third unseen-game proof pending

## User outcome

Give the tool a Ren'Py game or readable script and receive a trustworthy, readable whole-story
timeline without spending weeks adapting the application to that game. The timeline must explain
chronology, choices, conditions, nested routes, important state, destinations, rejoins, loops,
endings, and explicit uncertainty.

## Current evidence

The Resort of Temptation v0.2.2 hybrid Story Atlas is the first complete proof of the selected
architecture. It froze deterministic facts and 1,103 execution-derived corridors before editorial
AI, integrated every corridor exactly once, and passed independent structural and rendered-Chrome
audits.

That proof used a game already studied during the failed-app diagnosis and repair. It validates the
hybrid assembly contract but does not establish generalization to a new third game.

The detailed architecture is [HYBRID_APPROACH.md](../../HYBRID_APPROACH.md). The decision history is
[PROJECT_HISTORY.md](../../PROJECT_HISTORY.md).

## Next proof

Use one genuinely unseen third game with no app-specific preparation:

- keep the original input read-only;
- run the reusable deterministic extractor unchanged;
- source-check one representative branch/state section;
- freeze execution-derived corridor packets;
- inspect the first ten corridors plus difficult structural cases;
- render one real section in a scrolling prototype;
- continue to full-game summaries only after those gates pass; and
- independently audit both structure and the rendered result.

If a parser defect appears, preserve the unchanged failure and correct only the generic cause. The
repaired run receives a new identity and cannot be reported as unchanged success.

## Smallest implementation

- Keep deterministic parsing, control flow, state provenance, evidence, and unresolved facts in
  Python.
- Export one compact reusable fact package and one execution-derived corridor package.
- Keep AI output in a strict editorial-only schema.
- Use a first-ten plus structural-proof canary before parallel summaries.
- Assemble a static dossier and simple full-width scrolling Atlas from stable IDs.
- Add only the product seams demonstrated necessary by the third-game proof.

## Exclusions

- No claim that the existing Story River app is fixed end to end on Resort.
- No claim of cross-game generalization from the Resort hybrid proof.
- No new River styling, graph canvas, pan/zoom, mobile UI, or production workflow platform before
  the third-game gate.
- No AI-created choices, conditions, edges, effects, ownership, destinations, rejoins, loops, or
  endings.
- No guessed dynamic behavior.
- No supplied game archive, extracted game tree, generated Atlas, transcript, or disposable project
  committed to Git.

## Acceptance checks

1. The unchanged deterministic extractor completes or preserves a precise generic failure.
2. One real section proves correct chronology, branch ownership, nesting, state provenance,
   destination, rejoin, loop/terminal classification, and source evidence.
3. Every story-bearing statement is included exactly once or explicitly excluded.
4. The canary prose is concrete, source-grounded, and mechanically unchanged.
5. The prototype is useful in Chrome before full-game editorial work begins.
6. Full integration has no missing, duplicate, unexpected, or structurally altered corridor.
7. Independent source/structure and rendered-browser audits pass.
8. Timing and manual intervention are recorded honestly.
9. Unresolved behavior remains visible and is never converted into a confident route.
10. The result establishes whether a simple Atlas, text dossier, or adapted River should become the
    reusable product surface.

## Current code correction boundary

The generic region-hierarchy repair prevents shared checklist hubs from forming recursive parent
cycles and adds downstream hierarchy validation. Focused tests pass. The old durable Story Map V2
publication path still requires a fresh broad nested-lineage canary before it can be called fixed on
Resort. M16 does not depend on claiming that legacy path is complete.
