# Ren'Py Story Mapper project state

Updated: 2026-08-03

## Active work

- Active milestone: M16 Hybrid story mapping and third-game proof.
- Contract: [`docs/milestones/M16_HYBRID_STORY_ATLAS/GOAL.md`](milestones/M16_HYBRID_STORY_ATLAS/GOAL.md).
- Task ledger: [`docs/milestones/M16_HYBRID_STORY_ATLAS/TASKS.md`](milestones/M16_HYBRID_STORY_ATLAS/TASKS.md).
- Architecture: [`docs/HYBRID_APPROACH.md`](HYBRID_APPROACH.md).
- Historical narrative: [`docs/PROJECT_HISTORY.md`](PROJECT_HISTORY.md).
- Native Codex goal: none.

## Status summary

The last accepted integrated app baseline is the painted Story River merged through PR #36 at
commit `1c2f246`. It remains valid evidence for the Ms. Denvers development game.

The current direction changed after the Resort of Temptation v0.2.2 benchmark:

- the unchanged app failed in `canonical_graph` before AI or River publication;
- direct source analysis produced a useful sourced dossier quickly but was not independently
  exhaustive;
- a generic hierarchy correction made the deterministic pipeline complete and acyclic;
- the old all-at-once Story Map publication route still failed the required canary/model/lineage
  acceptance boundary; and
- a separate hybrid run successfully froze deterministic facts and corridors, added editorial AI,
  built a static Story Atlas, and passed independent structural and Chrome audits.

The hybrid is now the selected architecture. It has not yet replaced the integrated app and has not
yet passed a third unseen game.

## Current product decision

For a new game, prove story value in this order:

1. deterministic source/control/state extraction;
2. one source-checked real section;
3. execution-derived corridor freeze;
4. first-ten plus difficult-structure editorial canary;
5. one real rendered prototype;
6. full editorial parallelization only after the first gates pass;
7. exact-once integration; and
8. independent structure and Chrome audits.

Do not make River polish or the old durable AI workflow the first test of whether the game can be
understood.

## Resort benchmark result

### Unchanged current app

- Reached 523 labels, 47,543 nodes, 47,971 edges, 619 arms, 565 state effects, 203 gates, 18 loops,
  and 95 terminal nodes.
- Failed at `canonical_graph` with `builtins.RecursionError`.
- `canonical_availability=none`.
- Published story events/arcs/claims: 0/0/0.
- Provider requests: 0.
- Readable Story River: none.
- Source-sampled grade: 0 PASS, 0 PARTIAL, 10 FAIL.
- Time to conclusive failure: approximately 10 minutes 16 seconds.

### Direct clean-slate analysis

- First useful sourced explanation: approximately 11 minutes 15 seconds.
- Full dossier plus independent structure/state audits: approximately 36 minutes 12 seconds.
- Source-sampled grade: 8 PASS, 2 PARTIAL, 0 FAIL.
- Required one-off extraction/audit scripts and a post-freeze named-menu semantics correction.

The benchmark recommendation was hybrid: retain deterministic evidence but stop treating canonical
Story River assembly and UI polish as the primary proof of value.

## Generic region-hierarchy correction

The canonical failure was caused by repeated/checklist menus. Broad reachability made shared
continuation hubs appear owned by several arms, producing cyclic parent chains.

The current correction:

- accepts a parent only when the child split belongs to exactly one parent arm;
- deterministically clears a cycle's outer root;
- leaves ambiguous shared regions unparented;
- rejects malformed hierarchy before recursive M10/M11 traversal; and
- derives source-projection lineage from declared parents and raw unique arm ownership.

Focused tests and lint pass. A fresh Resort deterministic project completed with current M06/M10/
M11 results. This is a generic deterministic fix, not proof that the old Story Map publication path
is complete.

## Old publication-path boundary

A final zero-submit Resort attempt successfully prepared 166 pending jobs and made zero provider
calls. It stopped before AI because:

- the supported workflow had no exact-first-ten execution selector;
- its available provider bindings did not match the requested Luna/Max policy; and
- a broad Episode 3 sample found 15 direct nested arm-entry spans with incomplete local lineage in
  the legacy source-adapter publication path.

No database slicing, cache injection, or cancel-after-ten workaround was used. Before describing the
legacy path as fixed, rerun that Episode 3 lineage sample and the supported canary/publication flow.

## Hybrid Resort proof

The successful hybrid run froze:

- 35 verified source files;
- 523 labels, 47,543 nodes, and 47,971 edges;
- 1,103 story corridors containing 23,825 unique narrative statements exactly once;
- 101 choices, 177 conditions, and 620 exported arms;
- 565 effects, 203 requirements, 222 rejoins, 18 loops, and 95 structural terminals; and
- 557 explicit unresolved records.

The coordinator inspected a first-ten plus eight-item structural canary and a real Chrome prototype
before bulk work. Four parallel editorial batches completed the remaining 1,085 corridors after
focused repairs to generic prose. Exact-once integration passed. Independent structure audit passed.
Independent Chrome audit passed after three Atlas-only corrections for stale technical content,
navigation to filtered targets, and a stale empty-state message.

Timing:

- first useful story summary: approximately 47 minutes 40 seconds;
- first usable complete Atlas: approximately 1 hour 59 minutes 40 seconds;
- final audited freeze: approximately 2 hours 46 minutes 34 seconds.

This is complete and trustworthy for source-establishable Resort v0.2.2 structure. It is not an
unseen third-game proof and is not committed as a generated product artifact.

## Current operating rules

- Original game inputs remain read-only.
- Supplied game archives and extracted script trees stay out of Git.
- Python owns factual structure; AI owns editorial explanation only.
- Cloud AI is default unless the user requests local processing.
- Prove one real section before whole-game work.
- Inspect a first-ten canary before parallel editorial work.
- A failure in deterministic extraction, publication, or rendering remains a failure at that gate.
- Full-width desktop scrolling reader only; no pan/zoom/mobile scope.
- Dynamic behavior that source cannot establish stays explicitly unresolved.

## Next action

Run the M16 hybrid contract on a genuinely unseen third game. Do not choose the permanent reader UI
or invest in more River polish until that proof shows whether the fact package, corridor boundaries,
canary, and audited full result generalize without a game-specific rewrite.

## Authority

1. The user's latest explicit instruction.
2. Repository `AGENTS.md` and [`MASTER_PLAN.md`](MASTER_PLAN.md).
3. The active [M16 goal](milestones/M16_HYBRID_STORY_ATLAS/GOAL.md).
4. This project-state pointer.

Older milestone files are historical evidence. They do not control the active UI, provider, model,
testing, or orchestration decision unless the current authority explicitly adopts them.
