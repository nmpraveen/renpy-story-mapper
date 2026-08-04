# Ren'Py Story Mapper project history

Updated: 2026-08-03

## Why this document exists

This is the durable narrative of how the project changed, what was accepted, what failed, and why
the current direction is hybrid. It is written for a future developer or AI that has the GitHub
repository but none of the original Codex conversations or generated local evidence.

The exact implementation history remains in Git and the milestone reports. This document explains
the decisions connecting those commits. It deliberately distinguishes four different claims:

1. a parser or transport completed;
2. deterministic story facts were produced;
3. a readable story was rendered and accepted on one game; and
4. an approach generalized to a genuinely new game.

The first three have been demonstrated at different points. The fourth has not.

## Current position in one page

- The repository began as a safe, read-only Ren'Py archive analyzer and grew into a local Windows
  story-mapping application with durable projects, a browser interface, deterministic graph/state
  analysis, optional AI organization, route solving, and a scrolling Story River.
- The original development game, Ms. Denvers, drove nearly all product design. By 2026-08-01 its
  accepted reader could show a full story with choices, conditions, nested routes, state backlinks,
  destinations, rejoins, endings, search, and painted tributaries.
- A second-game benchmark on Resort of Temptation v0.2.2 exposed a generalization failure. The
  unchanged app stored substantial source/control/state data but failed in `canonical_graph` with a
  `RecursionError`, published no story, made no provider request, and rendered no River.
- Clean-slate source analysis produced a useful sourced explanation in 11 minutes 15 seconds and a
  complete dossier plus audits in 36 minutes 12 seconds. It was much more useful than the failed app,
  but it needed one-off scripts and still produced two partial findings in a ten-case audit.
- A generic region-hierarchy repair fixed the canonical recursion. A later attempt still showed that
  the old all-at-once Story Map publication path lacked a supported first-ten execution boundary,
  could not bind the requested model policy, and retained a broader source-lineage risk.
- The successful hybrid proof reused deterministic Python facts, froze execution-derived corridors,
  checked a first canary, parallelized only editorial summaries, and rendered a separate static Story
  Atlas. It mapped 1,103 corridors and passed independent structure and Chrome audits.
- That hybrid proof used the already studied Resort release after diagnosis. It is strong evidence
  for the architecture, not evidence that a third unseen game will work unchanged.
- The next decisive test is a third unseen game. Further River polish or a large product migration
  should wait until the hybrid fact/corridor contract passes that test.

## Chronological milestone map

| Date | Milestone | What changed | Main lesson |
|---|---|---|---|
| 2026-07-10 | M01 | Safe RPA inventory, inert parser, source-linked control-flow graph | Read game data without executing it |
| 2026-07-10 | M02 | Deterministic scenes, beats, and normalized transitions | Story presentation must retain graph authority |
| 2026-07-10 | M03 | SQLite projects, incremental refresh, requirements, effects, state metadata | Preserve expensive analysis and provenance durably |
| 2026-07-10/11 | M04 | Native PySide6 three-level bounded graph | Technically navigable is not the same as an easy story |
| 2026-07-11/12 | M05 | Optional AI organization and review workflow | AI can explain groups but cannot own mechanics |
| 2026-07-12 | M06 | Unified source recovery and temporary/persistent route semantics | Input recovery and branch semantics are separate problems |
| 2026-07-12 | M06.5 | Local loopback browser replaces the native shell as primary UI | Keep Python authority while simplifying presentation |
| 2026-07-12/13 | M07/M07.1 | Two-level Route Map, resumable parallel AI, stronger safety | Durable workflow grew faster than user-facing story value |
| 2026-07-13 | M08/M09 | Web-only product, evidence ownership, archive authority, metadata | Names can enrich facts but must not create topology |
| 2026-07-14 | M10 | Canonical graph, guard/state provenance, exact inspection | Canonicalization became powerful and structurally complex |
| 2026-07-14/15 | M11 | Human scenes and chapters above M10 | Human grouping must not corrupt branch ownership |
| 2026-07-15/18 | M12/M13 | Route solver and optional AI narrative layer | Correctness, caching, budgets, and lifecycle added heavy machinery |
| 2026-07-24/27 | M15.1 Phases 01-04 | Story Map V2 and full-game 425-section checkpoint | Chunk transport was still defining the visible story |
| 2026-07-28/31 | M15.1 Phase 05 | Progressive state-aware timeline and accepted family-tree reader | Build story corridors from execution flow before summarizing |
| 2026-07-31/08-01 | M15.2 Phase 06 | Story River, two visual rejections, accepted painted flow | A presentation proof is game-specific until benchmarked elsewhere |
| 2026-08-02/03 | Unseen-game benchmark | Unchanged app versus direct source analysis on Resort | App failed; direct was useful; hybrid was recommended |
| 2026-08-03 | Repair and publication attempt | Generic hierarchy fix; old publication workflow stopped before AI | Fixing canonicalization did not automatically fix the full product path |
| 2026-08-03 | Hybrid Story Atlas | Frozen facts + corridors + editorial AI + static reader | Current preferred direction; third-game proof remains pending |

## Era 1 - Safe deterministic foundation

### M01: archive analyzer and inert parser

The project started as a narrow Windows tool: point it at Ren'Py source or an RPA archive and obtain
a deterministic, source-linked graph without running the game. M01 delivered bounded archive
inventory, restrictive unpickling, `.rpy` preference, inert parsing of labels/menus/conditions/
jumps/calls/returns, explicit unresolved nodes, and stable JSON. The original acceptance handled an
8,000-node graph while proving the source archive remained unchanged.

This established the product's most durable rule: source structure is data, not executable
instructions. See [M01 completion](milestones/M01/COMPLETION_REPORT.md).

### M02 and M03: semantic projection, state, and durable projects

M02 grouped adjacent narration/dialogue into scenes and beats only across proven fallthrough. It
kept choices, conditions, calls, returns, merges, endings, and unresolved mechanics as hard
boundaries. M03 added durable SQLite projects, incremental refresh, deterministic requirements and
effects, user-facing variable metadata, corruption checks, backups, and cancellation.

These milestones were necessary for repeatability, but they also began a recurring tension: the
repository could preserve more exact evidence than a normal reader wanted to see.

- [M02 completion](milestones/M02/COMPLETION_REPORT.md)
- [M03 completion](milestones/M03/COMPLETION_REPORT.md)

### M04: first visual product

M04 exposed the analysis in a native PySide6 application with three levels: overview, structural
events, and exact evidence. Pan, zoom, fit, paging, search, worker threads, and a 240-item rendering
cap kept the technical graph bounded.

It proved that the graph could be navigated safely, but it was still a graph-inspection product.
Users had to interpret technical nodes rather than simply read the story from top to bottom.
That mismatch would recur through several later designs.

See [M04 completion](milestones/M04/COMPLETION_REPORT.md).

## Era 2 - Optional AI, route maps, and the local browser

### M05: AI-organized Story Explorer

M05 added optional cloud organization. Deterministic graph facts stayed authoritative; AI could
name and summarize proposed arcs/events, every result remained a reviewable draft, and local
fallback still worked. Independent review caught fail-open model selection, incomplete cache
identity, and claim evidence not bound to its target. Those were fixed before acceptance.

The important architectural result was positive: AI was useful for editorial organization. The
operational cost was also visible: strict schemas, caches, consent, repairs, review states, and
provider boundaries were becoming a product of their own.

See [M05 completion](milestones/M05/COMPLETION_REPORT.md).

### M06 through M09: broader inputs and a browser-only Route Map

M06 introduced safe `.rpyc` recovery through a pinned isolated helper, unified folder/file/archive
ingestion, and route regions that distinguish temporary detours from persistent routes. M06.5 moved
the supported presentation into a local loopback browser while leaving analysis in Python.

M07 reduced the visible interface to a two-level Route Map plus Detail/Evidence and built a durable,
parallel, resumable organization engine. M07.1 tightened consent, recovered-source acknowledgement,
budget accounting, generation binding, and real-project browser behavior. M08 removed the obsolete
native graph UI, enforced evidence ownership throughout the AI pipeline, and made the browser-only
story map the product. M09 made exact `scripts.rpa` the story authority while treating `extras.rpa`
as metadata only.

This era solved many genuine correctness and safety problems. It also accumulated scheduling,
checkpoint, retry, cache, budget, persistence, and browser workflow machinery before the basic
question - "Can I quickly read the whole game?" - was settled.

- [M06 completion](milestones/M06/COMPLETION_REPORT.md)
- [M06.5 completion](milestones/M06.5/COMPLETION_REPORT.md)
- [M07 completion](milestones/M07/COMPLETION_REPORT.md)
- [M07.1 completion](milestones/M07.1/COMPLETION_REPORT.md)
- [M08 completion](milestones/M08/COMPLETION_REPORT.md)
- [M09 completion](milestones/M09/COMPLETION_REPORT.md)

## Era 3 - Canonical graph, human scenes, route solving, and narrative workflow

### M10: canonical graph authority

M10 consolidated labels, branch regions, guard dependencies, state facts, witnesses, search, and
inspection into one canonical graph. Hardening fixed predicate provenance, bounded guard
propagation, edge reachability, predecessor proofs, canonical search, unchanged refresh reuse, and
headless acceptance.

The canonical graph became the strongest reusable technical asset in the repository. It also
became a high-risk convergence point: if hierarchy construction was malformed, every downstream
scene, summary, and reader depended on it.

See [M10 completion](milestones/M10/COMPLETION_REPORT.md) and the
[canonical contract](milestones/M10/CANONICAL_GRAPH_CONTRACT.md).

### M11: human scenes and chapters

M11 converted canonical atoms into human scenes while keeping exact M10 topology. Early grouping
over-segmented the game into thousands of small scenes and browser ordering allowed overlapping
positions. The correction derived scene precedence from canonical edges, projected scene flow,
treated only supported narrative/location evidence as strong boundaries, and preserved unresolved
or disconnected procedures as explicit hard cuts.

The central lesson was that human grouping is editorial even when deterministic: it must be
rebuildable without changing mechanical authority.

See [M11 completion](milestones/M11/COMPLETION_REPORT.md).

### M12 and M13: solver and optional narrative layer

M12 answered "How do I reach this outcome?" through bounded static path solving. Review fixes
handled contradictory states, nested return frames, prefix growth, and loop phase/exit accuracy.
M13 added an optional route-aware narrative layer with durable resume, budget accounting, citation
navigation, cache replay, and strict non-transmission boundaries. Several review cycles corrected
cross-phase cumulative usage and reopened-reservation accounting.

Both milestones were technically successful, but they reinforced the scope problem: the repository
was becoming a production workflow platform while the user wanted a quick personal story checker.

- [M12 completion](milestones/M12/COMPLETION_REPORT.md)
- [M13 completion](milestones/M13/COMPLETION_REPORT.md)

## Era 4 - Story Map V2 and the scope reset

### Why the product was reset

By late July, the current system could ingest, persist, schedule, recover, audit, and render a great
deal of data. The visible story still followed request chunks and technical groups. Phase 04 reached
a 425-section whole-game checkpoint, but those 425 sections were transport units rather than human
story events. A cloud provider attempt returned no accepted summaries; a later local mapping pass
filled the sections, but the reader remained long and repetitive.

The Phase 04 closeout explicitly recorded that the work had become a production-grade platform
project rather than a quick script-to-story tool. The user chose to preserve the useful code and
replace the acceptance standard.

See [Phase 04 closeout](milestones/M15_PHASE_04/COMPLETION_REPORT.md).

### The rejected 34-section result

An attempted recovery of saved summaries produced a compact 34-section outline and appeared to
complete many mapping calls. Source review showed that it was not a trustworthy story map:

- choices were attached to the wrong story points;
- branch arms were missing;
- nested choices were flattened;
- local continuations were presented as endings;
- destinations were opaque;
- long summaries were clipped; and
- transport completion was mistaken for factual correctness.

That result was revoked. Historical counts such as 103 successful calls or 105 chunks are retained
only as operational evidence, never as story acceptance.

## Era 5 - Progressive state-aware story and the family-tree reader

### Phase 05 contract

Phase 05 replaced chunk-owned presentation with an execution walker:

1. Python follows entry, labels, fallthrough, jumps, calls, returns, menus, conditions, and direct
   state changes.
2. Linear statements between control points become corridors.
3. Every corridor retains branch membership, state provenance, destination, rejoin, loop, terminal,
   unresolved state, and source evidence.
4. AI summarizes only after those corridor boundaries are frozen.
5. The browser attaches summaries beneath the exact Python-owned story point.

The first real proof was a Terrance route. The first rendering still stacked technical cards, hid
the actual story behind vague phrases such as "the encounter escalates," and did not read as a
branch tree. The corrected version used concrete expandable prose, compact sibling forks, full-width
descendants, semantic colors, explicit technical disclosures, and true rejoin/ending distinctions.
The user accepted that proof on 2026-07-28.

### Whole-game Phase 05 result

The progressive method then accounted for all 149 parser labels in Ms. Denvers. A graph-backed
packetizer produced 597 narrative packets from 604 chains and accounted for all 12,191 reachable
narrative statements: 12,183 included and eight explicitly excluded as non-story text. The first
ten summaries were inspected before four parallel workers completed the remaining 587. All 597
passed factual-fidelity review; 594 reader-visible corridors were placed exactly once.

The whole-game reader retained 324 controls and 700 arms in authority, with 260 controls and 571
arms in the default story and technical/startup material moved into secondary detail. Follow-up
work corrected cross-label ownership, machine-derived names, state backlinks, destination/rejoin
navigation, collapsed descendants, route-wide prose, completed-workflow chrome, ARIA, search, and
desktop overflow. The user accepted the Phase 05 family-tree reader on 2026-07-31.

- [Phase 05 goal](milestones/M15_PHASE_05/GOAL.md)
- [Phase 05 task ledger](milestones/M15_PHASE_05/TASKS.md)
- [Phase 05 readiness review](milestones/M15_PHASE_05/SEMANTIC_REVIEW.md)

## Era 6 - Story River design

Phase 06 changed presentation, not story authority. Shared chronology became a central river;
choices and conditions became colored tributaries; persistent routes retained identity until a
proven rejoin or terminal; and a route panel followed the current reading position.

The visual design required three attempts:

1. **Rejected colored family tree.** The facts and interactions were correct, but the page was the
   Phase 05 tree with route colors and thin connectors. It did not resemble a river.
2. **Rejected CSS bars.** Thick borders, rectangles, and clipped polygons created rigid straight
   bands. They could not curve, taper, flare, or merge naturally.
3. **Accepted painted river.** `river.js` measured the laid-out DOM and painted one local SVG layer
   per event: trunk, mouth flare, bezier tributaries, confluence, tapered terminal tails, and
   route-owned streams. CSS continued to own cards, typography, and color.

The final proof preserved fitting-room route ownership, nested B.1/B.2 routes, confluence and state
navigation, panel synchronization, light/dark themes, wide forks, and zero horizontal overflow at
the tested desktop widths. It was accepted on 2026-08-01 and merged through
[PR #36](https://github.com/nmpraveen/renpy-story-mapper/pull/36).

This was a real product achievement on Ms. Denvers. It was not yet a cross-game benchmark.

- [Phase 06 goal](milestones/M15_PHASE_06/GOAL.md)
- [Phase 06 implementation plan](milestones/M15_PHASE_06/IMPLEMENTATION_PLAN.md)
- [Phase 06 task ledger](milestones/M15_PHASE_06/TASKS.md)

## Era 7 - The unseen-game benchmark

### Benchmark design

Resort of Temptation v0.2.2 was supplied as game number two. Two tracks were frozen before
comparison:

- **Current app unchanged:** no code, prompt, schema, model, or game-specific fix was allowed.
- **Direct clean-slate analysis:** workers could read source and write small disposable extractors,
  but could not use the Story Mapper implementation or Ms. Denvers artifacts.

The comparison was based on source-grounded cases rather than counting completed calls.

### Unchanged-app result

The app imported enough data to record 523 labels, 47,543 nodes, 47,971 edges, 619 arms, 565 state
effects, 203 gates, 18 loops, and 95 terminal nodes. It then failed in `canonical_graph` with
`builtins.RecursionError`. Canonical availability was `none`; story events, arcs, claims, provider
attempts, and River output were all zero. The browser correctly reported that the project had no
readable story map.

This was a conclusive app failure, not a partially successful River. Time to conclusive failure was
10 minutes 16 seconds. In the ten-case audit the app graded 0 PASS, 0 PARTIAL, and 10 FAIL because it
produced no consumable story.

### Direct-analysis result

Direct source reading produced the first useful sourced story explanation in 11 minutes 15 seconds
and the full dossier plus structural/state audits in 36 minutes 12 seconds. It explained the main
chronology, meaningful routes, nested choices, long-range state, loops, dynamic uncertainty, and
local versus real endings. The audit graded 8 PASS, 2 PARTIAL, and 0 FAIL.

The direct route was not magically exhaustive. It needed two game-specific extractors and three
workers. One audit also misread a named Ren'Py menu as an undefined label; official Ren'Py semantics
show that `menu NAME:` creates a jumpable control point, and the frozen finding was corrected in a
separate reconciliation. Another immediate rejoin was structurally found but narratively thin.

The benchmark therefore rejected both extremes: the current app did not generalize, while pure
prose was useful but still benefited from deterministic fact checks. The recommendation was hybrid.

## Era 8 - Generic repair and the limit of the old publication path

### Canonical recursion root cause

The original region-parent algorithm treated broad arm reachability as branch nesting. Resort uses
repeating menus and checklist loops where a shared continuation hub is reachable through several
arms. Those shared nodes appeared to own one another, creating cyclic parent chains and recursive
canonical traversal.

The generic repair:

- accepts a parent only when the child split is owned by exactly one parent arm;
- preserves the deterministic smallest candidate selection;
- detects parent cycles and clears a deterministic outer root;
- leaves shared or ambiguous regions unparented;
- rejects duplicate, missing, invalid, or cyclic downstream hierarchy before recursion; and
- builds source-projection lineage from declared parent links and raw unique arm ownership instead
  of broad descendant reachability.

A fresh Resort deterministic run then completed: canonical M10 and scene M11 payloads were current,
acyclic, and selected. Focused tests passed. No AI or Story River publication occurred in that run,
so it was correctly described as a deterministic repair rather than an end-to-end app fix.

### Final bounded publication attempt

A later zero-submit preparation created 166 pending Story Map jobs with no provider attempts. The
old workflow was stopped before AI for three reasons:

1. it could execute only the complete frozen plan and had no supported exact-first-ten selector;
2. its supported model bindings did not match the requested Luna/Max policy; and
3. a broader Episode 3 audit found 15 nested arm-entry spans whose local lineage was still
   incomplete in the old source-adapter publication path.

No SQLite slicing, cache injection, or cancel-after-ten workaround was used. The reusable
deterministic facts were preserved, and the product conclusion moved to the hybrid route.

## Era 9 - Hybrid Story Atlas proof

### What "hybrid" meant in the successful run

The hybrid run did not ask AI to rebuild the graph and did not use the old all-at-once Story Map
publication workflow. It used this sequence:

```text
read-only source
  -> deterministic fact export
  -> execution-derived corridor packets
  -> frozen first canary and structural proof set
  -> AI titles/summaries only
  -> static dossier and scrolling Story Atlas
  -> independent structural audit
  -> independent rendered Chrome audit
```

Python owned every control, arm, corridor, condition, effect, requirement, destination, rejoin,
loop, terminal, unresolved record, and source reference. AI could write only editorial fields and
supporting evidence references.

### Result

The proof mapped:

- 35 verified source files;
- 523 labels, 47,543 nodes, and 47,971 edges;
- 1,103 story corridors containing 23,825 unique narrative statements exactly once;
- 101 choices, 177 conditions, and 620 exported arms;
- 565 effects and 203 long-range requirements;
- 222 rejoins, 18 loops, and 95 structural terminals; and
- 557 explicit unresolved records that were displayed rather than guessed.

The coordinator checked the first ten execution-order corridors plus eight difficult structural
proof corridors. A real-section prototype passed in Chrome before four parallel workers summarized
the remaining 1,085 corridors. Mechanical or generic bulk prose was rejected and repaired only in
the affected batches; accepted work was not unnecessarily rerun. Integration proved exact-once
coverage with no missing, duplicate, unexpected, or structurally altered corridor.

Independent structure audit passed. The first independent Chrome audit found three presentation
defects: technical selection retained story cards, navigation could land on search-hidden targets,
and a stale empty-state message remained below the technical inventory. Static Atlas-only fixes
closed all three. The final reader passed nested branches through depth three, conditions, evidence,
search, filters, state/destination/rejoin links, endpoint labeling, long scrolling, console checks,
and horizontal-overflow checks.

The first useful summary arrived in about 47 minutes 40 seconds. The first complete usable Atlas
arrived in about 1 hour 59 minutes 40 seconds. Final audited freeze was 2 hours 46 minutes 34 seconds
from T0.

### Orchestration/model issue

The run initially requested Luna/Max with Fast mode on. Three workers visibly launched without Fast
mode, were stopped immediately, and wrote no files. The user then explicitly replaced that setting
with Sol/Medium and Fast mode off. Ten productive user-visible tasks completed the foundations,
prototype, four summary batches, structural audit, and Chrome audit. This history is recorded as an
execution fact, not a permanent architecture requirement.

### What the proof does not establish

- It does not prove the integrated Story River app works on Resort.
- It does not prove the old durable AI-publication workflow is fixed.
- It does not resolve the 557 source-incomplete mechanics.
- It does not prove runtime behavior for dynamic screens, timers, replay exits, or opaque Python.
- It does not prove unseen-game generalization because Resort was already studied during diagnosis.
- It does not choose the final reusable UI. The current Atlas is a static proof artifact.

The durable architectural contract is documented in [HYBRID_APPROACH.md](HYBRID_APPROACH.md).

## Repeated troubles and the fixes that mattered

| Trouble | Why it happened | Effective correction |
|---|---|---|
| Technical graphs were hard to read | UI mirrored parser/storage structure | Progressive execution corridors and secondary evidence |
| AI groups changed story shape | Transport chunks were treated as events | Python freezes membership and mechanics before AI |
| 34-section outline looked complete but was wrong | Call completion was mistaken for story correctness | Source-grounded branch/state audit and revocation |
| 425 sections were repetitive | Request chunks defined visible sections | Execution-derived corridors and human grouping |
| Vague summaries hid actual events | Prompts optimized for short consequences | Concrete corridor summaries with first-ten review |
| Cross-label story appeared under the wrong route | Labels were rendered separately from owning arms | Arm-owned route flow and canonical shared continuations |
| Machine identifiers leaked into the reader | Names were derived from stable IDs | Accepted deterministic wording overrides and raw Python as detail |
| River looked like a colored tree | Presentation decorated old boxes | Redesign around a visible central flow |
| River looked like straight bars | CSS borders/polygons could not curve | Local measured SVG painter |
| New game crashed canonicalization | Shared checklist hubs formed cyclic parent links | Unique-arm parent rule, deterministic cycle break, invariant checks |
| Direct audit called a named menu undefined | Tooling assumed only `label` creates a target | Reconcile against Ren'Py named-menu semantics |
| Old publication could not honor first-ten/model policy | Workflow froze and executed the whole plan | Separate run-level corridor canary outside that workflow |
| Bulk summaries became templated | Failed prompt pattern was scaled too far | Reject affected batches and repair only failed records |
| Atlas links landed on invisible cards | Filters/scope state were not cleared during navigation | Reveal ancestors, select scope, clear filters, then navigate |
| Model/Fast setting was not actually applied | Task API and UI exposed different controls | Stop before work, record the mismatch, obtain explicit override |

## Current authority and next chapter

The accepted integrated baseline remains the Phase 06 Story River on Ms. Denvers. The current
product direction is the hybrid architecture, documented in
[PROJECT_STATE.md](PROJECT_STATE.md) and the
[M16 goal](milestones/M16_HYBRID_STORY_ATLAS/GOAL.md).

The next decisive work is intentionally smaller than another month of UI development:

1. give the hybrid pipeline a third unseen game with read-only source;
2. freeze deterministic facts and one representative corridor section before full-game work;
3. check a first-ten plus difficult-structure canary;
4. render and inspect a real prototype;
5. proceed to the whole game only if those gates pass without game-specific parser fixes; and
6. choose whether the durable product should be a simplified Atlas, a text-first report, or an
   adapted River only after that evidence exists.

## Repository and input boundary

No supplied game archive, extracted game tree, prompt transcript, generated Atlas, or benchmark
database belongs in Git. The repository ignores `*.rpa`, `artifacts/`, `output/`, and `tmp/`.
Tracked documentation contains counts, decisions, and limitations but not the supplied game files.

## Primary historical references

- [Master plan](MASTER_PLAN.md)
- [Current project state](PROJECT_STATE.md)
- [M15 Phase 04 closeout](milestones/M15_PHASE_04/COMPLETION_REPORT.md)
- [M15 Phase 05 accepted baseline](milestones/M15_PHASE_05/GOAL.md)
- [M15 Phase 06 Story River](milestones/M15_PHASE_06/GOAL.md)
- [M16 hybrid goal](milestones/M16_HYBRID_STORY_ATLAS/GOAL.md)
- [Merged pull requests](https://github.com/nmpraveen/renpy-story-mapper/pulls?q=is%3Apr+is%3Amerged)
