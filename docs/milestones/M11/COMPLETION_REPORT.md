# M11 human story scenes and chapters completion report

## Completion status

M11 implementation and validation are complete on `codex/m11-human-scenes`. Creation of the
non-draft review pull request is explicitly approved; merge remains separately gated.

- Exact merged-main baseline: `cf6da9e076b6141713d4e8f71588fdbcd9ebc911`
- M10 remains the sole control-flow authority.
- M11 consumes the exact M10 source generation, canonical schema, and canonical payload hash.
- The M11 scene presentation is deterministic, local, and provider-free.
- The accepted M10 canonical payload hash remains
  `769c2931f284fa875a0b8d561d668fcfe21c4d7e0de83c3f09fad71e7d5f6a2f`; the matching source
  generation remains `fea15ae2bc2ce1d8561c54549d8c8b69a7ed355ac93a06c6f077593868f3c77f`.

## Delivered model

- Exactly one deterministic story atom owns every M10 canonical node. Canonical nodes, edges,
  regions, and facts have explicit one-entry coverage accounting.
- Every possible scene cut has an immutable boundary decision with accepted/rejected status,
  hard/strong/weak/conflict strength, rule version, canonical anchors, bounded reason, and exact
  node/edge/region/fact/evidence/proof provenance.
- Temporary M10 detours are separate branch containers. Their ordered arms may own zero, one, or
  multiple arm-local scenes, retain nested temporary containers, and rejoin at the exact M10 merge
  without becoming persistent lanes. Expanded arms have exclusive scene ownership; an arm-local
  scene cannot contain a sibling-arm atom, exact merge, or post-merge continuation.
- Narrative calls are represented by stable call-site occurrences referencing canonical atoms.
  Shared callees retain distinct caller contexts; technical helpers may remain collapsed; guarded
  calls retain fact provenance.
- Only M10 persistent-route and terminal-split arms become separate lanes. Nested lanes retain the
  exact canonical parent arm plus split/merge anchors. A shared callee never implies a merge.
- Scenes belong to exactly one chapter and lane. Explicit source chapter/day markers are
  conservative; inputs without reliable markers use the neutral `Story` chapter.
- Canonical loop regions retain repeatable scene status, hub membership, return-to-hub records,
  and partial order. Overlapping loop regions may share a scene while the scene retains one stable
  primary hub.
- Minimal reviewer corrections support split-before-atom and adjacent-scene merge overlays. The
  correction service rebuilds only assembly/presentation, publishes atomically, and performs no
  writes when the same overlay is already current.

## Durable processing

M11 persists exactly four whole-corpus phases:

1. `story_atoms`
2. `scene_boundaries`
3. `scene_assembly`
4. `scene_presentation`

Each checkpoint is durable and content-bound. Final publication is atomic. A failed newer M11
build retains the last complete M11 publication, while selection refuses to mix that publication
with a different current M10 generation. An unchanged project reuses all four M11 phases without
backup or writes. The measured linear rebuild was adequate, so M11 did not add source windows,
scope schedulers, dirty-neighbor propagation, or cross-generation scope reuse.

## Presentation

The packaged app now opens the deterministic `Scenes` view first when a current M11 publication is
available. It presents chapter bands, story/persistent lanes, scene cards, temporary choices, and
call-site occurrences. Map responses are limited to 30 nodes and 180 relationships; detail is
limited to 60 model-membership references and 60 canonical/evidence membership references. Map
metadata shares a 240-reference budget. Occurrence detail presents the referenced callee narrative
while retaining separate caller-scene context. Lanes, chapters, scenes, boundaries, temporary
branches, and call occurrences all provide direct provenance/source escape. The scene-map path
does not decode the M10 canonical payload. Detail loads the exactly paired canonical graph only
for provenance/evidence. If M11 is missing or stale, the app explicitly falls back to M10
Inspection.

## Acceptance summary

- Focused M11 release suite plus M10 phase-persistence regression: 49 passed in 8.57 seconds.
- Full Windows pytest: 655 of 656 passed in the first final run; the sole failure was the
  pre-existing M06 2.0-second wall-clock assertion at 2.178 seconds, which passed in isolation at
  1.95 and 1.84 seconds. A second run encountered the same timing assertion plus transient Windows
  socket exhaustion; both unrelated tests passed in isolation.
- Real Chrome acceptance: passed at 100% and 200%, with no overflow, remote request, provider
  construction, or browser error.
- Persisted 500/1,000/2,000 scale acceptance: passed both linear and scene-rich workloads, exact
  coverage, and approximately 2x payload/model growth on both doubling intervals. The scene-rich
  runs produced 502, 1,002, and 2,002 scenes.
- Private MsDenvers acceptance: 9,120 atoms, 4,076 scenes, 102 temporary containers, 13 lanes,
  exact 18,683-record coverage, and a bounded initial page.
- Private ground truth now checks M11 output directly: four choice containers, eight ordered arms,
  four canonical rejoin chains, 16 representative memberships, four nested-lane parents, and zero
  illegal story-procedure cuts.
- Private performance: 6.043-second cold M11 publication, 6.537-second replay, 2.523-second
  unchanged full refresh, 21,051,805 M11 payload bytes, and 256,344,064 final SQLite bytes. The
  unchanged-refresh diagnostic target was missed in this run; it is explicitly not a release
  blocker.
- Private replay phase hashes and model hash were identical. The original M10 project, recovered
  source, and archive were unchanged; provider constructions and remote requests were zero.
- Scene-quality diagnostics found 337 singleton scenes (8.268%); atom-count median 2, p75 2, p90
  3, p99 5, and maximum 17. Accepted boundaries were 3,784 hard and 7 strong, with no accepted
  weak/conflict boundary. Eighteen privacy-safe records cover the four reviewed Day 1 choices and
  rejoins; the diagnostic found no severe segmentation error and did not retune production rules.
- A clean detached-worktree package build produced both sdist and wheel; 382 package entries were
  inspected with no output, handoff, cache, project, archive, executable, or absolute-path leak.

Exact commands, results, limitations, performance-target interpretation, and artifact paths are in
`VALIDATION_REPORT.md`.

## Explicit M11 non-goals

M11 does not implement AI narrative titles or summaries, character motives, full-plot summaries,
route-to-target solving, path-requirement solving, runtime tracing, dynamic framework adapters, or
global AI stitching. It does not rebuild control flow, infer a new merge, execute game/creator
Python, duplicate canonical source text into phase payloads, or claim weak scene boundaries are
objectively final.

M12 retains route-to-target solving. M13 retains optional evidence-linked narrative review and may
not alter M10 authority. M14 retains dynamic adapters and optional runtime tracing and remains
deferred.

## Handoff

Independent contract re-review found no remaining P0 or P1 issue. The review pull request is
authorized; stop after creating it and await review without merging or beginning M12.
