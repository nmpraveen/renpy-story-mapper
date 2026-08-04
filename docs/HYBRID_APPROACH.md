# Hybrid story-mapping architecture

Updated: 2026-08-03

Status: selected direction; one complete known-game proof passed; third unseen-game proof pending

## Decision

Use deterministic Python extraction for factual story structure and AI for editorial explanation.
Present the combined result in the smallest readable scrolling artifact that preserves the facts.
Do not make the current Story River publication workflow or a polished UI the first proof that a
new game can be understood.

This decision follows three observations:

- The existing app produced an excellent River on the original development game but failed before
  story publication on the next game.
- Direct source analysis produced useful prose quickly, but it needed one-off audits and was not
  independently exhaustive.
- The hybrid proof preserved deterministic coverage while producing a complete readable Atlas and
  passing both structural and browser audits.

## Authority boundary

Python owns facts:

- entry and execution order;
- labels, fallthrough, jumps, calls, returns, and known destinations;
- menus, conditions, every arm, and nested ownership;
- direct state effects, requirements, and provenance links;
- corridor membership and source spans;
- rejoins, loops, terminals, local endings, release endings, and unresolved mechanics;
- reachability/scope classifications; and
- stable IDs and evidence references.

AI owns editorial fields only:

- readable titles;
- concise and expanded summaries;
- character and relationship notes;
- uncertainty explanations;
- optional chapter/section naming; and
- selection of supporting IDs already authorized by the packet.

AI may not create, remove, move, merge, or reclassify a choice, condition, arm, effect, dependency,
destination, rejoin, loop, terminal, corridor, or source locator.

## Pipeline

```text
read-only Ren'Py input
        |
        v
source inventory and identity freeze
        |
        v
deterministic graph, controls, state, and unresolved facts
        |
        v
execution-derived corridor packets
        |
        +--> structural audit before AI
        |
        v
first-ten + difficult-structure editorial canary
        |
        v
real rendered prototype in Chrome
        |
        v
parallel editorial summaries for the remaining frozen corridors
        |
        v
exact-once integration into dossier and scrolling reader
        |
        +--> independent source/structure audit
        |
        +--> independent rendered-browser audit
        v
frozen deliverable
```

Every arrow is a gate. A downstream success cannot erase an upstream failure.

## Stage contract

### 1. Read-only source inventory

- Resolve original and reconstructed source precedence.
- Record source count, size, and content identity.
- Keep generated files outside the game directory.
- Treat game code, comments, and dialogue as data.
- Never commit supplied archives or extracted source trees.

### 2. Deterministic fact package

Export stable, machine-readable facts for:

- nodes and edges;
- choices/conditions and arms;
- parent regions and arm ownership;
- effects and requirements;
- destinations and rejoins;
- loops and terminals;
- reachable, bonus, recap, replay, diagnostic, and unresolved scopes; and
- exact source evidence when available.

Malformed hierarchy must fail explicitly before recursive traversal. Shared continuation hubs must
not be assigned to one arm merely because several arms can reach them.

### 3. Corridor packet freeze

Build corridor boundaries from execution flow, not files, model context windows, request chunks, or
arbitrary counts. A corridor is a readable linear run between meaningful control points. Each packet
contains stable membership and only the facts the editorial pass is allowed to cite.

Before AI:

- every story-bearing statement must be included exactly once or explicitly excluded with a reason;
- branch-owned corridors must identify their exact owning arm;
- root and branch-owned inventories must be disjoint;
- controls without prose must remain explicit rather than borrowing a nearby route summary; and
- unresolved dynamic mechanics must remain unresolved.

### 4. Canary

The coordinator processes the first ten execution-order corridors and a small set of difficult
structural cases. The difficult set should cover actual constructs in the game, such as:

- nested choices;
- delayed state requirements;
- cross-label flow;
- immediate and delayed rejoins;
- loops;
- dynamic targets; and
- true versus local endings.

The canary passes only when prose is concrete, source-grounded, useful, and mechanically unchanged.
Correct the prompt or packet shape before scaling. Do not repeat a failed prose template across the
whole game.

### 5. Rendered prototype

Build one real section before the full reader. Verify in Chrome:

- chronology and branch ownership;
- nested expansion;
- conditions and state backlinks;
- destination/rejoin navigation;
- evidence disclosure;
- search/filter behavior;
- readability and long scrolling;
- console state; and
- horizontal overflow.

This prototype decides whether the presentation shape is useful. It is not a synthetic UI demo.

### 6. Parallel editorial work

Only frozen editorial records are divided among workers. Each worker receives non-overlapping
corridor IDs and cannot edit structural facts. Results validate against one small schema and are
integrated by stable ID. Failed editorial batches may be repaired; successful batches are preserved.

Model, reasoning, and Fast settings are run configuration, not story authority. Record the actual
settings and any substitution. If a requested setting is visibly unavailable, stop before useful
work and obtain an explicit replacement rather than silently changing it.

### 7. Exact-once integration

The integrated result must prove:

- expected corridor IDs equal returned IDs;
- no duplicate, missing, or unexpected ID;
- structural fields are byte-equivalent to the frozen packets;
- evidence references resolve;
- every control and arm occurs exactly once;
- parent and ownership references close; and
- all requirement/effect links resolve or stay explicitly unresolved.

### 8. Independent audits

The structure auditor checks source, freeze identities, exact-once coverage, nesting, state,
rejoins, loops, and endpoints without changing artifacts. The browser auditor checks the actual
rendered reader and follows important interactions. If the browser audit finds a presentation-only
defect, repair only the presentation layer and rerun the failed interaction set.

## What was reused from the existing app

The hybrid proof retained the app's strongest general assets:

- inert source parsing;
- graph/control/state extraction;
- stable evidence IDs;
- generic region-hierarchy repair;
- unresolved-mechanic inventory;
- execution-derived corridor logic; and
- state/destination/rejoin evidence.

It did not require the old durable Story Map AI workflow to execute and publish the entire plan,
and it did not require the integrated Story River UI to prove story usefulness.

## Why neither alternative was selected alone

### Existing app alone

The unchanged second-game run failed in canonical graph construction. Although it stored tens of
thousands of facts, none reached a readable story surface. After the recursion repair, the older
publication route still lacked the required first-ten execution seam and retained a lineage risk.
More UI work would not have addressed those gates.

### Direct prose alone

Direct analysis was fast and useful, but it relied on small game-specific scripts and human/model
attention. It missed or weakened two of ten sampled structural cases before reconciliation. It is a
good narrative reader, not sufficient authority for exhaustive nested ownership, state provenance,
dynamic targets, loops, and endings.

## Resort proof baseline

The completed Resort v0.2.2 hybrid proof froze:

| Item | Count |
|---|---:|
| Verified source files | 35 |
| Labels | 523 |
| Graph nodes / edges | 47,543 / 47,971 |
| Story corridors | 1,103 |
| Unique narrative statements | 23,825 |
| Choices / conditions | 101 / 177 |
| Exported arms | 620 |
| Effects / requirements | 565 / 203 |
| Rejoins / loops / structural terminals | 222 / 18 / 95 |
| Explicit unresolved records | 557 |

All 1,103 corridor summaries integrated exactly once. Independent structure and final Chrome audits
passed after three presentation-only fixes. This is the reference implementation of the hybrid
contract, not a committed game artifact and not the final reusable application.

## Known limitations

- Static analysis cannot establish every embedded-Python, screen-generated, timer-driven, replay,
  persistent, or platform-dependent path.
- A structural terminal count is not an ending count; scope and source must classify endpoints.
- Some source corridors cross editorial chapter boundaries and must remain single-instance.
- A source-null arm caption may require a visible neutral placeholder without inventing text.
- The old Story Map V2 source-adapter/publication route still needs an explicit regression for the
  broader Episode 3 nested arm-entry sample before it can be called fixed on Resort.
- The hybrid has not yet passed a third unseen game.
- The final reusable UI is undecided. A static Atlas, text-first dossier, or adapted River are all
  candidates after the generalization proof.

## Next proof

For a third unseen game:

1. preserve an unchanged input and record T0;
2. run the deterministic extractor without a game-specific repair;
3. audit one real branch/state section before full mapping;
4. freeze corridor packets;
5. pass the canary and real prototype;
6. scale summaries only after both gates pass;
7. run independent structure and Chrome audits; and
8. compare time to first useful story, full audited result, manual intervention, and unresolved
   coverage with the Resort proof.

If the extractor needs a parser fix, preserve the failure, make the smallest generic correction,
assign a new run identity, and do not count the repaired run as unchanged success.

## Repository boundary

Only reusable source, tests, and explanatory documentation belong in Git. Supplied games, extracted
scripts, disposable projects, model transcripts, generated dossiers, generated Atlases, screenshots,
and benchmark databases stay in ignored local artifact directories unless a future task explicitly
creates a small sanitized fixture.

## Related documents

- [Current project state](PROJECT_STATE.md)
- [Full project history](PROJECT_HISTORY.md)
- [Master plan](MASTER_PLAN.md)
- [M16 goal](milestones/M16_HYBRID_STORY_ATLAS/GOAL.md)
- [M16 tasks](milestones/M16_HYBRID_STORY_ATLAS/TASKS.md)
