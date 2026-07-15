# M11 proposal — human story scenes and scene/chapter presentation

- Status: planning only; implementation requires explicit approval
- Planning branch: `codex/m11-human-scenes-plan`
- Baseline: merged `main` at `cf6da9e076b6141713d4e8f71588fdbcd9ebc911`
- Proposed model schemas: `m11-story-atoms-v1`, `m11-scene-model-v1`, and
  `m11-scene-presentation-v1`

## 1. Milestone outcome

M11 will turn the M10 canonical inspection graph into a deterministic, human-readable scene map.
The route map will use chapters as containers, scenes as its primary story units, temporary choices
as nested scene content, and persistent route splits as separate lanes. Detail view will retain
exact dialogue, narration, requirements, effects, unresolved behavior, and source evidence.

M11 succeeds when a reader can follow the scene/chapter shape of a large Ren'Py story without
mistaking labels for scenes, technical statements for story events, or temporary choices for
persistent routes.

This proposal does not authorize implementation. No M11 production code, schema migration, test,
fixture, or UI change is part of the planning branch.

## 2. Authority boundary

The selected, complete M10 canonical graph is the only control-flow authority consumed by M11.
M11 must not call M01, M02, M06, or M07 builders; repeat reachability, dominator,
post-dominator, strongly connected component, call/return, branch-region, or route-classification
analysis; or infer an edge, split, merge, arm member, terminal, or lane that M10 does not expose.

The M11 input contract is:

1. a valid `m10-canonical-graph-v1` payload;
2. a matching `source_generation` and canonical payload hash from the analysis state;
3. canonical nodes, edges, regions, facts, evidence, proofs, and embedded route attributes; and
4. optional static M09 display metadata, used only for source-authored names and categories.

M09 metadata may name a scene, character, or progression variable. It cannot change scene
membership, chapter order, branch membership, reachability, or lane topology. Every structural
M11 decision must point back to M10 records. M11 is a replaceable derived read model: it never
mutates the canonical graph.

If the M10 canonical payload is absent, invalid, partial, or generation/hash-incoherent, M11 does
not build a current model. It may retain the last-good M11 model as explicitly stale, paired only
with the exact older canonical generation and hash from which it was derived.

## 3. Deterministic story atoms

A story atom is the smallest M11-owned presentation unit and the stable anchor for boundaries and
user corrections. Atom construction is a typed projection, not narrative interpretation.

### Atom kinds

The initial closed vocabulary is:

| Kind | Canonical basis | Presentation role |
|---|---|---|
| `dialogue` | Source-backed script unit with a statically identified speaker/text form | Human story content |
| `narration` | Source-backed narrative statement | Human story content |
| `visual_change` | Static scene/show/hide/transition statement | Boundary signal or detail |
| `choice` | Canonical choice split and its ordered M10 arms | Nested interactive structure |
| `condition` | Canonical condition and ordered M10 arms | Conditional detail |
| `state_change` | Canonical effect fact attached to a node or edge | Story-state detail |
| `call` | Canonical call-enter/summary/return records | Collapsible structural detail |
| `loop` | Canonical loop record and proof | Visible structural warning/detail |
| `terminal` | Canonical terminal node and classification | Ending/update/dead-end marker |
| `unresolved` | Canonical unresolved node, edge, region, or fact | Explicit uncertainty marker |
| `technical` | Source-backed or synthetic canonical material not classified above | Collapsible coverage |

Each atom owns exactly one primary canonical node. Structural group records may reference several
atoms only when their membership is already declared by one M10 region or call-site proof. For
example, a choice atom owns the canonical split node while its nested choice group references the
ordered arm atoms and merge. M11 never groups arbitrary connected nodes merely because they look
similar.

Each atom records:

- a stable ID derived from the M11 atom schema, atom kind, and primary canonical node/origin IDs;
- ordered canonical node, edge, region, and fact IDs;
- M10 reachability and resolution status without reinterpretation;
- evidence and proof IDs, relative source spans, and line-basis fields by reference;
- deterministic content fields already present in canonical source text/metadata;
- story-facing versus technical classification and the rule that assigned it; and
- a canonical coverage disposition for every referenced M10 record.

Atom IDs exclude timestamps, durations, run IDs, output paths, and presentation order. The same
canonical input and algorithm version therefore produce byte-identical atoms. All in-scope M10
nodes must be either owned by exactly one atom or listed once in a bounded coverage table with a
reason such as `synthetic_merge_anchor`, `collapsed_call_support`, or `unreachable_technical`.
Nothing silently disappears.

## 4. Automatic human scene boundaries

Scene discovery is a deterministic partition over atoms and M10 region boundaries. It uses a
versioned rule set with inspectable decisions; it is not AI, statistical clustering, textual
summarization, or label-equals-scene grouping.

### Boundary precedence

The boundary rules are evaluated in this order:

1. **Hard chapter boundaries.** A source-authored chapter/day marker or a proven canonical
   progression effect starts a chapter and therefore a scene. A progression category may come
   from M09 metadata, but the actual anchor must be an M10 canonical fact/evidence record.
2. **Persistent topology boundaries.** An M10 `persistent_route` or `terminal_split` arm entry,
   proven persistent-lane merge, and terminal creates a scene boundary at the corresponding
   canonical anchor.
3. **Source-authored scene boundaries.** A statically extracted explicit scene title is accepted
   at its canonical source anchor. A visual `scene` reset is a strong signal only when reinforced
   by a resolved transfer, label entry, progression change, or a minimum narrative run; routine
   background changes alone do not fragment scenes.
4. **Structural narrative boundaries.** Resolved non-technical label transfers, source/module
   discontinuities, and terminal-to-entry transitions may start a scene when they separate two
   nontrivial narrative runs. Labels alone are only evidence, never final scene ownership.
5. **Fallback.** With no supported boundary signal, atoms remain in the current scene. A story
   with no chapter evidence receives one neutral `Story` chapter rather than invented chapters.

Rules include fixed minimum-content and hysteresis bounds to avoid one-line scenes. Hard chapter,
persistent-route, terminal, and unresolved-safety boundaries are exempt from the minimum.
Technical-only runs attach to the nearest supported scene or become explicit technical coverage;
they do not create human scenes by themselves.

Every proposed boundary has a stable decision record containing the rule version, signal kind,
canonical anchors, evidence/fact/proof IDs, accepted/rejected status, and bounded reason. The UI
can therefore explain “why this is a scene” without generating prose about what the scene means.

### Region safety

Automatic segmentation must not cut between a temporary split and its proven M10 rejoin. When a
normal boundary signal lands inside such a region, it is moved outward to the split or post-merge
continuation according to the fixed rule. If incompatible hard chapter signals occur in different
arms, M11 records a boundary conflict and keeps the canonical structure visible as unresolved
presentation instead of guessing a scene partition.

Nested M10 regions are processed inside-out. Parent ownership resumes at the nested region's M10
immediate post-dominator, matching the canonical ownership contract rather than flattening nested
arms.

## 5. Temporary choices and rejoins inside scenes

M10 regions classified as `local_detour`, `optional_detour`, or
`reconvergent_route_segment` remain inside one scene when they have a proven merge and do not
contain an incompatible hard boundary.

The scene stores a nested choice group with:

- the canonical split atom;
- ordered arms copied from M10 arm ordinals;
- per-arm atom membership, captions, gates, effects, terminals, and unresolved flags;
- the canonical merge and its proof; and
- the post-merge continuation atom.

Nested temporary choices remain nested within the owning arm. They do not become route-map lanes,
top-level scenes, or duplicated “possible timelines.” The route-map scene card may show a compact
choice/rejoin marker; exact arms are opened in Detail and Evidence.

A choice without a proven rejoin, a terminal arm, or unresolved transfer is not presented as a
temporary rejoining choice. M11 uses the M10 classification/status and surfaces the uncertainty;
it does not search for a likely later rejoin.

## 6. Persistent route splits as lanes

Only M10 `persistent_route` and `terminal_split` regions create separate lanes. Lane IDs derive
from the canonical region ID and arm origin, and lane order follows the M10 arm ordinal and
embedded route order.

At a persistent split:

- common scenes remain on the parent spine up to the split;
- each arm's scenes are placed on a separate child lane;
- nested persistent splits create nested lane identities without flattening ancestry;
- a lane rejoins only at the exact merge declared by M10; and
- terminal or unresolved lanes remain separate through their last supported atom.

Matching source labels, similar text, shared callees, or later visual similarities never merge
lanes. Calls shared by several routes are referenced as shared detail and are not used to claim
that the routes rejoined. M11 also does not enumerate all combinations of nested route arms.

## 7. Scene and chapter hierarchy

The M11 structural hierarchy is:

```text
scene model
└── chapter (source title or neutral deterministic ordinal)
    ├── spine lane
    │   └── scene
    │       ├── ordered story atoms
    │       └── nested temporary choice groups
    └── persistent child lane(s)
        └── scene(s)
```

Chapters are ordered containers. Scenes are ordered only within a lane; M11 does not invent one
global ordering between mutually exclusive lanes. A chapter may span a persistent split, with
each lane retaining the same chapter anchor, or a proven per-lane progression marker may start a
lane-local chapter segment. Shared post-merge material returns to the parent lane at the exact M10
merge.

Source-authored static titles are preferred. Otherwise scenes receive neutral deterministic labels
such as `Scene 12` plus an optional source locator; chapters use `Chapter 3` or `Story`. M11 does
not fabricate narrative titles or summaries.

This hierarchy does not add a third user-visible navigation level. The two product levels remain:

- **Route Map:** chapter bands containing scene nodes and persistent lanes, with compact nested
  choice/rejoin indicators; and
- **Detail and Evidence:** the selected scene's atoms, temporary arms, local predecessor/successor
  context, requirements, effects, exact text, source spans, and provenance.

## 8. Minimal split/merge corrections

M11 permits only two structural correction primitives:

1. **Split scene before atom:** add a boundary at an existing atom boundary within the same
   chapter and lane.
2. **Merge adjacent scenes:** remove the shared boundary between immediately adjacent scenes in
   the same chapter and lane.

The same boundary primitive may correct a chapter break only when both sides share the same lane
topology. Corrections cannot move an atom, reorder content, cross persistent lanes, cut an M10
temporary split/rejoin region, merge across an unresolved/terminal boundary, alter a gate/effect,
or edit any canonical node, edge, region, fact, evidence, or proof.

Corrections are stored as a small overlay keyed by stable atom and boundary anchors. Automatic
output remains reproducible without the overlay; applying the same ordered overlay to the same
model is also reproducible. On refresh, a correction is replayed only when its anchors and topology
still match. Missing or changed anchors become an orphaned correction requiring review rather than
being silently retargeted.

Renaming, free-form scene summaries, arbitrary drag/move, lane editing, graph edge editing, and
bulk manual chronology are outside the M11 correction surface.

## 9. Source and canonical-graph provenance

Every M11 payload is paired with:

- `source_generation`;
- `canonical_schema` and `canonical_graph_hash`;
- M11 schema and deterministic rule-set versions; and
- an optional advisory metadata hash, kept separate from structural authority.

Atoms reference canonical records and their direct source evidence. Scene membership references
atom IDs and canonical region/edge anchors. Boundaries reference the canonical facts, nodes,
edges, evidence, and proofs that triggered them. Chapter and lane records reference their boundary
and M10 region derivations. Corrections reference the generated boundaries they add or suppress.

The M11 normalized structural hash includes ordered membership, lane ancestry, chapter/scene
boundaries, canonical references, and deterministic derivations. It excludes timestamps, phase
durations, run IDs, transient errors, absolute paths, and correction audit timestamps.

The UI provides direct escape from every scene, choice, lane, boundary, and chapter to exact M10
canonical inspection and then to source evidence. M11 never replaces or hides the canonical view.

## 10. Incremental processing and durable partial results

M11 adds a separate generation-bound phase state rather than weakening M10's completeness rules.
The proposed phases are:

1. `story_atoms` — validate/pair M10, classify atoms, and persist bounded atom scopes;
2. `scene_boundaries` — evaluate boundary decisions and region-safe nesting per scope;
3. `scene_assembly` — assemble chapters, scenes, lanes, coverage, and correction results; and
4. `scene_presentation` — build the bounded browser index and search/detail records.

Atom and boundary work is divided into deterministic bounded scopes using canonical label/region
anchors and fixed-size source-ordered windows with a small incident-edge halo. Each scope has an
input digest over only the canonical records and metadata fields it consumes. A successful scope
is committed transactionally as a checkpoint before the next scope begins.

On cancellation, crash, or failure:

- completed current-generation checkpoints remain durable;
- the state records the failed phase/scope, sanitized code, duration, completed/total scope counts,
  and coverage;
- resume revalidates input digests and skips coherent checkpoints;
- a current partial model is served only with an explicit partial badge and coverage gaps; and
- the last-good complete M11 model remains available as stale, still paired with its exact older
  canonical generation/hash.

No view combines current atoms with a stale hierarchy, or an M11 hierarchy with a different M10
canonical hash. Final scene assembly and presentation publication are atomic. Partial checkpoints
are never mislabeled complete.

For changed input, unchanged atom scopes are reused only when their normalized canonical subset
digest is identical under the new generation. Dirty scopes include the changed scope, its boundary
neighbors, and any containing M10 region/lane assembly. Global recomputation is required only when
the relevant M10 topology or M11 rule/schema version changes. Correction replay runs after the
new deterministic assembly and preserves or flags overlays by stable anchors.

An unchanged refresh extends the M10 no-write fast path: it validates the stored M11 generation,
canonical hash, model hash, checkpoints, correction overlay binding, and presentation generation,
then reports all four M11 phases as reused with no M11 rebuild, backup, or write.

## 11. Presentation behavior

The browser opens to the scene map when a current or explicitly stale complete M11 model is
available. It keeps the existing canonical inspection as a clearly labeled technical view.

The scene map must:

- start near 30 scene nodes and remain within the existing 30-node/180-edge response bounds;
- show chapter bands, a common spine, and separate persistent lanes;
- render temporary choices as compact nested split/rejoin markers inside their scene;
- distinguish unresolved, terminal, stale, and partial coverage without helper-text clutter;
- preserve pan, zoom, fit, search, filters, selection, and canonical/source escape;
- search scene labels, exact dialogue/narration, choice captions, facts, and source locators; and
- remain usable at Windows 100% and 200% display scaling without horizontal-page overflow.

Detail view shows deterministic content, not an AI description. It may display counts and literal
labels such as “3 choices” or “rejoins here,” because those are direct structural facts.

## 12. Private MsDenvers performance behavior

The accepted M10 private baseline is 52 authoritative recovered sources plus 5 secondary extras,
9,120 canonical nodes, 9,238 canonical edges, a 161,312,664-byte canonical payload, and a
235,261,952-byte SQLite project. The accepted timings are 23.041 seconds for first analysis,
11.139397 seconds for the canonical phase, and 1.427 seconds for an unchanged refresh.

M11 must be designed for this corpus rather than only small fixtures:

- Atom, boundary, and assembly algorithms must be linear in the consumed canonical records plus
  emitted membership references. There is no all-pairs reachability, path enumeration, arm-product
  expansion, or global stitching pass.
- Canonical text/evidence is referenced by ID rather than copied into every atom, scene, chapter,
  search row, and lane.
- One canonical decode/index pass is shared across M11 phases; bounded adjacency and region indexes
  replace repeated scans of the 161 MB payload.
- Cold M11 processing should add no more than 8 seconds on the accepted Windows authority machine,
  keeping first analysis at or below 32 seconds under the same private harness conditions.
- An unchanged refresh should remain at or below 2.0 seconds, perform zero M11 scope work and zero
  M11 writes, and reuse all M10 and M11 phases.
- M11 payloads and indexes should add no more than 32 MiB to the private project, keeping the
  accepted database below 300 MiB. Source/evidence text duplication is a release blocker.
- Initial scene-map API responses remain bounded to 30 nodes and 180 edges; browser acceptance at
  100% and 200% must not materialize the whole graph.
- A single-source change must report reused/rebuilt M11 scope counts and must not rebuild unrelated
  atom scopes. Any full M11 invalidation must name the topology/schema/rule reason.

The private acceptance run will repeat same-project refresh and separate fresh replay. Atom,
scene, chapter, lane, boundary, nesting, coverage, and normalized presentation hashes must match.
The game folder and archive must retain identical SHA-256, size, and modification time; provider
constructions and remote requests remain zero.

## 13. Validation and acceptance plan

### Synthetic contracts

Fixtures will cover:

- stable atom identity and complete canonical coverage;
- multiple human scenes inside one label and one scene spanning several labels;
- visual resets that do and do not create boundaries;
- chapter/day markers and the neutral single-chapter fallback;
- temporary choices, nested temporary choices, exact rejoins, and post-merge continuation;
- persistent, terminal, nested, and later-proven-merge lanes;
- shared calls that do not imply route reunion;
- loops, dead material, unresolved transfers, and boundary conflicts;
- split/merge correction replay, rejection, and orphaning;
- cancellation after each phase/scope, durable resume, stale/partial labeling, and atomic publish;
- unchanged and targeted-change reuse; and
- exact canonical/evidence escape for every M11 record type.

### Private ground truth

The existing independently authored MsDenvers Day 1 ground truth will be extended by direct source
inspection, not analyzer output, with expected chapter/scene anchors, temporary choice ownership,
the four accepted choice/rejoin chains, persistent-lane examples, and representative provenance.
Acceptance compares exact anchors and memberships where ground truth is explicit and reports
coverage elsewhere; it does not score similarity against an AI-generated answer.

### Release gates

M11 completion requires:

- full Windows CPython 3.12 pytest plus focused M11 contracts;
- Ruff, strict mypy, `pip check`, JavaScript syntax, and isolated wheel install/import;
- deterministic normalized hashes across unchanged refresh and fresh replay;
- cancellation/resume and injected-failure checks for every M11 phase;
- browser acceptance at 100% and 200% with bounded payloads and exact provenance traversal;
- private MsDenvers correctness, performance, immutability, provider, and network checks;
- migration/open/refresh compatibility for existing M10 projects;
- independent review with no unresolved P0-P2 finding; and
- M11 goal, task ledger, contract, validation, completion report, and native infographic artifacts.

## 14. Proposed implementation sequence after approval

1. Freeze atom, scene, boundary, lane, provenance, and state schemas with synthetic contract tests.
2. Implement the canonical-only atom projection and complete coverage validation.
3. Implement deterministic scene/chapter boundary decisions and temporary-region nesting.
4. Implement persistent lane assembly and normalized scene-model hashing.
5. Add checkpoint persistence, partial/stale state, resume, incremental invalidation, and correction
   overlays.
6. Build the bounded scene/chapter presentation and canonical/source escape paths.
7. Add synthetic, browser, scale, and private MsDenvers acceptance and performance hardening.
8. Run independent review, close findings, document validation, and prepare one approval-gated PR.

Each step stays on the approved M11 branch and must preserve M10 canonical hashes for identical
source input. The PR remains unmerged until separately approved.

## 15. Explicit M11 non-goals

M11 does not include:

- rebuilding, correcting, or competing with M10 control-flow authority;
- new reachability, split/merge discovery, call/return analysis, route classification, or arbitrary
  expression satisfiability;
- AI narrative titles or scene summaries;
- character motive, intent, relationship interpretation, or thematic inference;
- chapter, route, or full-plot summaries;
- route-to-target solving, path requirement solving, or playthrough enumeration;
- runtime tracing, game execution, creator Python execution, or dynamic framework adapters;
- global AI stitching or any provider/network call;
- image/audio/video analysis, thumbnails, hosted service work, installer work, or game editing;
- replay/gallery chronology merging; or
- arbitrary manual graph, lane, chronology, atom-membership, gate, effect, or source editing.

Those boundaries preserve M12 for route solving, M13 for optional evidence-linked AI narrative
work, and deferred M14 for dynamic adapters/tracing.

## 16. Approval gate

Approval of this proposal would authorize M11 implementation beginning with schema/contract tests.
Until that approval, work stops at this planning document.
