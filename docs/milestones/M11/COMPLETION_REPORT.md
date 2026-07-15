# M11 human story scenes and chapters completion report

## Correction status

The bounded three-P1 correction requested on PR #20 is implemented and validated on
`codex/m11-human-scenes`. The existing five M11 commits and architecture are retained. PR #20
remains open for final review; merge and M12 remain separately gated.

- Exact merged-main baseline: `cf6da9e076b6141713d4e8f71588fdbcd9ebc911`
- M10 remains the sole control-flow authority.
- M11 consumes the exact M10 source generation, canonical schema, canonical nodes, canonical
  edges, regions, facts, and structural ownership.
- Accepted M10 canonical payload hash:
  `769c2931f284fa875a0b8d561d668fcfe21c4d7e0de83c3f09fad71e7d5f6a2f`
- Matching source generation:
  `fea15ae2bc2ce1d8561c54549d8c8b69a7ed355ac93a06c6f077593868f3c77f`
- M10 hashes and private input fingerprints are unchanged. M11 provider constructions, remote
  requests, and game/creator Python executions remain zero.

## Delivered correction

### Browser ordering

M11 browser normalization maps numeric `page_order` to RouteGraph's numeric `order`; `ordinal` is
only a fallback. The browser regression loads at least ten same-lane scene nodes, proves one
rendered card per loaded node, verifies distinct graph positions, and rejects identical x/y
coordinates for any same-lane pair. The committed 100% and 200% review captures were regenerated.

### M10 story order and scene flow

Atom ordering now derives primary precedence from existing resolved M10 canonical edges within
each lane and temporary arm. Existing route order and source location remain deterministic
tie-breakers only. M11 neither invents edges nor repeats control-flow analysis. Resolved canonical
edges that cross scenes project into bounded, deduplicated `scene_flow` relationships with exact
canonical-edge provenance, so ordinary common-spine scenes are visibly connected while branches,
calls, loops, lanes, and exact rejoins retain their M10 topology and partial order.

### Human boundary semantics

Hard boundaries remain hard for chapters, persistent-lane ownership, terminal and unresolved
safety, module safety, unrelated procedures, and exact M10 topology. A visual `scene` reset is a
strong candidate accepted only when deterministic location/progression/transfer evidence or the
versioned minimum narrative-run rule reinforces it. Routine `show` and `hide` operations are weak
rejected candidates. A resolved normal continuation into a label can remain inside one human
scene. Rejected decisions and their full provenance remain durable for optional later review.

## Model and durability retained

- Exactly one deterministic story atom owns every M10 canonical node, with exact node/edge/region/
  fact coverage.
- Temporary choices remain nested containers with ordered arms and exact rejoins; persistent
  splits alone become separate lanes.
- Narrative calls remain call-site occurrences; shared callees do not imply merges.
- Scenes belong to exactly one chapter and lane; loops preserve repeatable membership and partial
  order.
- Split-before-atom and adjacent-scene merge corrections rebuild only assembly/presentation.
- The four content-bound phases remain `story_atoms`, `scene_boundaries`, `scene_assembly`, and
  `scene_presentation`; partials are durable, publication is atomic, and unchanged work is reused.

## Final acceptance summary

- Focused M11 suite plus M10 phase persistence: 54 passed in 10.78 seconds.
- Full Windows pytest: 660 passed and one unrelated M06 wall-clock assertion missed at 2.075
  seconds against 2.0; its immediate isolated rerun passed at 1.85 seconds. No M11 test failed.
- Ruff, strict mypy (70 source files), `pip check`, JavaScript syntax, package inspection, and
  `git diff --check` passed. The isolated wheel contained 91 entries and no forbidden artifacts.
- Real Chrome passed at 100% and 200%: 30 loaded nodes equaled 30 rendered cards/positions, all 14
  same-lane scene positions were distinct, 37 relationships rendered, and remote/provider counts
  were zero.
- Persisted linear and scene-rich 500/1,000/2,000 acceptance passed exact coverage and bounded
  approximately linear growth without imposing a universal scene-count target.
- Private MsDenvers acceptance passed with 9,120 atoms, 1,812 scenes, 102 temporary containers,
  13 lanes, exact 18,683-record coverage, and a 30-node/34-relationship initial map.
- Private cold/replay/unchanged-refresh times were 5.201/5.305/1.635 seconds; durable M11 payloads
  were 19,988,898 bytes and the final SQLite project was 255,279,104 bytes. All four diagnostic
  performance targets passed.
- Private replay phase/model hashes were identical. Four choices, eight arms, four exact rejoins,
  16 representative memberships, and four nested lane parents passed direct M11 checks.

The committed [scene-quality evidence](review-evidence/SCENE_QUALITY_EVIDENCE.md) reports the
authorized before/after boundary-rule distribution and 19 privacy-safe representative scene
sequences. The correction reduced the private draft from 4,076 to 1,812 scenes: singleton scenes
changed from 337 (8.268%) to 276 (15.232%), median atoms from 2 to 6, p75 from 2 to 6, p90 from 3
to 7, p99 from 5 to 10, and maximum from 17 to 25. The higher singleton percentage is reported,
not hidden: exact unresolved-safety and disconnected-procedure ownership account for the added hard
cuts. This is evidence about chronology, readability,
provenance, and structural ownership, not a universal target for scene count.

Exact commands, complete rule counts, browser captures, scale measurements, limitations, and
artifact links are in [the validation report](VALIDATION_REPORT.md).

## Explicit M11 non-goals

M11 does not implement AI narrative titles or summaries, character motives, full-plot summaries,
route-to-target or path-requirement solving, runtime tracing, dynamic framework adapters, or global
AI stitching. It does not rebuild M10 control flow, infer new merges, execute game/creator Python,
duplicate canonical source text into phase payloads, or claim weak scene boundaries are objectively
final.

M12 retains route-to-target solving. M13 retains optional evidence-linked narrative review and may
not alter M10 authority. M14 retains dynamic adapters and optional runtime tracing.

## Handoff

Only the three requested P1 findings were addressed. PR #20 is awaiting final review. Do not merge,
begin M12, or perform another broad implementation/architecture pass without new review feedback.
