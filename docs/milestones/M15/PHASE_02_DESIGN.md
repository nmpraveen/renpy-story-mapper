# M15.1 Phase 02 Story Map V2 design

Status: Frozen for early semantic review

Date: 2026-07-24

Integration base: `f914908621efb6ccf1728e3028c6176f961e5a7e`

## Boundary

The supported implementation is a new package:
`src/renpy_story_mapper/story_map_v2/`. It is a small one-pass mapping pipeline, not an extension
of `narrative_map` or its Stage H/E lifecycle.

```text
read-only source + current deterministic authority
  -> ordered scope lines and compact mechanics
  -> coherent source chunks
  -> one mapper response per chunk
  -> structural validation + Python mechanics overlay
  -> one chronological core record
```

The package may import only stable lower-level records and utilities needed for the operation:

- `canonical_graph_contract` for M10 nodes, edges, regions, facts, reachability, source evidence,
  and exact authority binding;
- `m11_scene_model` only for already-derived scene/lane/choice ownership and source order where it
  is useful, never as fine-atom allocation or a provider vocabulary;
- `m12_model`/`m12_solver` only for existing route-to-target status and stable destinations;
- current project/storage, source-navigation, safe ingestion, provider isolation, cancellation,
  and canonical JSON helpers.

It must not import `renpy_story_mapper.narrative_map`, `renpy_story_mapper.narrative`, or
`renpy_story_mapper.organization` in the supported V2 path. This keeps Stage H/E, adjacent-gap
voting, semantic hierarchy compilation, atom/evidence allocation, old persistence, and repair
machinery outside the architecture. A dependency test will enforce this boundary.

## Provider-neutral records

The source adapter emits one `StoryScope` containing:

- exact source identity and authority hashes;
- ordered `SourceSpan` records with relative path, physical line range, line-numbered raw text,
  label/scene boundary hints, and a stable source anchor;
- `ChoiceMechanic` records keyed by source choice location, with exact ordered arms, conditions,
  proven/possible effects, destination/rejoin facts, reachability, and unresolved warnings;
- compact density counts for menus, arms, conditions, transfers, and unresolved behavior.

The chunk planner emits ordered `StoryChunk` records. A chunk contains contiguous source spans,
its raw token estimate, density metrics, mechanics keys present in the chunk, and a packet hash.
It normally targets about 8,000 raw-story tokens, lowers the target near 5,000 for branch-heavy
material, prefers source/scene boundaries, and treats a menu plus arms plus nearby proven rejoin as
an indivisible cluster when that cluster fits under the 10,700-token ceiling. An indivisible
cluster above the ceiling fails preparation honestly rather than being silently cut or truncated.

The mapper request contains only:

- schema/prompt versions and chunk identity;
- line-numbered raw story text;
- the compact mechanics digest with opaque choice/arm keys;
- explicit instructions that the mapper supplies approximate story meaning only.

The mapper response is deliberately small:

- optional scope title and overview;
- ordered events with title, summary, valid source range, characters, and optional warning;
- ordered branch summaries referencing an existing choice key and arm order.

It contains no atom membership, evidence allocation, exact line coverage requirement, graph
coordinates, hierarchy levels, claim objects, repair locks, or stable AI prose hashes.

## Validation and mechanics overlay

Python validates that event ranges are ordered, nonempty, inside the chunk, and source-ordered; a
branch summary must reference a real deterministic choice key and arm ordinal. Invalid mapper text
does not alter authority.

The overlay always replaces any mapper rendering of path-critical fields with deterministic data:
exact captions, arm order, conditions, effects, destinations, rejoins, reachability, unresolved
status, and source navigation. AI punctuation or quoting around a caption is ignored. Setup/hint
controls are not promoted to story paths unless deterministic route authority classifies them as
story choices.

Every visible event gets a target anchor derived from authority/source identity and its first
source location. Every branch-specific event gets an anchor derived from the choice key, arm
ordinal, and deterministic destination/source location. Generated titles never participate in
target identity.

Accepted chunks assemble by source order. Wording is not required to replay byte-for-byte.
Missing, invalid, refused, or failed chunk summaries leave deterministic mechanics present and
make the overall record `partial`; they never trigger a generic manufactured summary or erase
other accepted chunks.

## Provider state transitions

```text
prepared --confirm exact preview--> confirmed --lazy construct cloud--> cloud submitted
cloud submitted --success--> cloud
cloud submitted --explicit content/safety refusal + fallback enabled--> verify loopback model
verify loopback model --exact match--> local submitted --success--> local_fallback
verify/local failure, fallback disabled, or any non-refusal cloud failure --> missing
cancel requested --> cancel active provider, retain completed chunks, submit no later chunks
```

The preview binds source, packet plan and hashes, prompt/schema, exact
`gpt-5.6-luna`/High/fast-off settings, call ceilings, transmitted field names, privacy exclusions,
and fallback choice. Any change requires a new preview and confirmation. Providers are constructed
only after confirmation.

Only an explicit hosted content/safety refusal can enter the local-fallback transition. Timeout,
rate limit, authentication, transport, invalid JSON/schema, identity mismatch, cancellation, and
ordinary quality failure remain missing/error states. The local packet is byte-identical to the
refused cloud packet. The loopback model must already be loaded and match
`qwen3.5-35b-a3b-uncensored-hauhaucs-aggressive`; the product never installs, starts, loads, or
unloads it.

## Ownership seams

- Track A owns records, adapter, chunking, mapper serialization/response validation, mechanics
  overlay, target anchors, assembler, generalized fixtures, and package dependency checks.
- Track B owns preview/confirmation identity, provider protocols, lazy cloud construction, error
  classification, refusal-only loopback fallback, accounting, cancellation, and fake-provider
  tests.
- Shared seams are `StoryChunk`, mapper request/response, `ChunkExecutionResult`, and
  `StoryMapCore`; neither track edits the other track's provider-neutral/provider-policy files.
- The coordinator owns shared-contract freeze, integration fixes, private inputs, live execution,
  acceptance artifacts, and Git/PR state.

## Checks mapped to risks

- Natural boundary, branch-density, rejoin-cluster, oversized-cluster tests prove chunk policy.
- Linear, local rejoin, persistent, nested, conditional, and unresolved fixtures prove mechanics
  overlay without private hard-coding.
- Range/order and invented choice/arm cases prove mapper validation.
- Fake all-cloud, refusal/fallback enabled, refusal/fallback disabled, local unavailable/identity
  mismatch, timeout, rate limit, bad JSON, cancellation, and partial assembly cases prove execution
  policy.
- Exact-caption quotation, setup-control filtering, stable target, and dependency/import tests
  prove the Python/AI and architecture boundaries.
- Relevant M10/M11/M12, ingestion, privacy/isolation, source-navigation, and package-import
  regressions protect lower-level authority.

## Explicitly not used

No Stage H or Stage E job, whole-scope hierarchy/editorial prompt, boundary vote, fine narrative
unit, atom membership, evidence-per-claim allocation, hierarchy compiler, semantic repair,
repair-lock protocol, old M15 publication path, or exact AI replay is called or adapted into this
pipeline. Historical code remains untouched and readable until Phase 05.
