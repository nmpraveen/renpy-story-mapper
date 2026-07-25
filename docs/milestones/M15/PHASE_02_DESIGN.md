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
- current project/storage, source-navigation, safe ingestion, and canonical JSON helpers.

It must not import `renpy_story_mapper.narrative_map`, `renpy_story_mapper.narrative`, or
`renpy_story_mapper.organization` directly or transitively in the supported V2 path. This keeps
Stage H/E, adjacent-gap voting, semantic hierarchy compilation, atom/evidence allocation, old
persistence, and repair machinery outside the architecture. A module-graph dependency test will
import every `story_map_v2` module, walk its transitive `renpy_story_mapper` imports, and fail if a
forbidden namespace is reachable.

Provider isolation is implemented inside the new package, not imported from a rejected/historical
semantic namespace. `story_map_v2/cloud_transport.py` is a minimal standard-library subprocess
boundary for the exact sterile Codex CLI request, identity verification, cancellation, and
sanitized result. `story_map_v2/loopback_transport.py` is a minimal standard-library HTTP boundary
restricted to `127.0.0.1`/`localhost`, exact loaded-model discovery, identical-packet submission,
cancellation, and sanitized result. They share only small V2 provider protocols and do not import
or modify the old cloud/local transports. Track B must prove the same isolation/privacy properties
with fakes before any live call.

## Provider-neutral records

The source adapter emits one `StoryScope` containing:

- exact source identity and authority hashes;
- ordered `SourceSpan` records with relative path, physical line range, line-numbered raw text,
  label/scene boundary hints, a stable source anchor, and Python-owned reachability plus retained
  unresolved warnings for the covered canonical nodes;
- `ChoiceMechanic` records keyed by source choice location, with exact ordered arms, conditions,
  proven/possible effects, destination/rejoin facts, reachability, and unresolved warnings;
- compact density counts for menus, arms, conditions, transfers, and unresolved behavior.

The chunk planner emits ordered `StoryChunk` records. A chunk contains contiguous source spans,
its raw token estimate, density metrics, the exact canonical compact mechanics JSON transmitted
with the raw story, mechanics keys present in the chunk, and a packet hash that binds both story
and mechanics bytes.
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

The validated core retains optional mapper scope title/overview text on the contributing chunk and
on the assembled core. Each accepted branch summary becomes a `CoreBranchOutcome` containing the
AI-written outcome meaning plus the Python-owned choice key, arm ordinal, exact caption, stable
anchor, reachability, and unresolved warnings. The compact core therefore does not discard the
provider contribution it validated.

## Validation and mechanics overlay

Python validates that event ranges are ordered, nonempty, inside the chunk, and source-ordered; a
branch summary must reference a real deterministic choice key and arm ordinal. Invalid mapper text
does not alter authority.

Before accepting an event, Python projects its source range to the current ordered source spans and
canonical node IDs, then derives each story-facing node's complete outer-to-inner arm lineage from
M10/M11 choice ownership. An event is branch-specific only when every covered story-facing node
has one identical nonempty lineage. A range that crosses sibling arms, mixes a branch arm with its
post-rejoin continuation, or otherwise contains incompatible lineages is rejected as an ambiguous
AI event; exact mechanics remain in the partial core. A shared/spine event may cover only nodes
with no arm lineage or one Python-proven shared continuation. The mapper never supplies or chooses
lineage. Per-arm branch summaries obtain their lineage exclusively from the referenced deterministic
choice key and arm ordinal, including any Python-owned nested parent lineage.

The overlay always replaces any mapper rendering of path-critical fields with deterministic data:
exact captions, arm order, conditions, effects, destinations, rejoins, reachability, unresolved
status, and source navigation. AI punctuation or quoting around a caption is ignored. Setup/hint
controls are not promoted to story paths unless deterministic route authority classifies them as
story choices.

Every visible event gets a target anchor from the source generation, canonical authority hash,
first covered canonical node ID, relative source path, and first physical line. A branch-specific
event additionally includes the complete ordered `(choice_key, arm_ordinal)` lineage and the
Python-owned deterministic destination ID. A branch-summary target uses the same inputs from its
referenced arm. Generated titles never participate in identity. Reachability is copied from the
bound canonical nodes and, when requested, the exact M12 destination result: `reachable` requires
confirmed reachable authority, `unreachable` requires a proven unreachable result, and any mixed,
dynamic, incomplete, or unknown result is `unresolved` with its warning retained.

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
prepared local_only --confirm exact preview--> verify loopback model
verify loopback model --exact match--> local submitted --success--> local_only
cancel requested --> cancel active provider, retain completed chunks, submit no later chunks
```

The preview binds source, packet plan and hashes, prompt/schema, exact
`gpt-5.6-luna`/High/fast-off settings, call ceilings, transmitted field names, privacy exclusions,
and execution mode/fallback choice. Any change requires a new preview and confirmation. Providers
are constructed only after confirmation. A `local_only` preview binds the same source, packets,
prompt/schema, transmitted fields, privacy exclusions, exact loopback endpoint/model, and local
call ceiling; it records zero planned/actual hosted submissions and never constructs the cloud
provider. Both local origins use the same packet bytes and record elapsed time, response hash,
usage when available, status, and sanitized reason.

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
  classification, self-contained cloud/loopback transports, refusal-only fallback, deliberate
  local-only execution, accounting, cancellation, and fake-provider tests.
- Shared seams are `StoryChunk`, mapper request/response, `ChunkExecutionResult`, and
  `StoryMapCore`; neither track edits the other track's provider-neutral/provider-policy files.
- The coordinator owns shared-contract freeze, integration fixes, private inputs, live execution,
  acceptance artifacts, and Git/PR state.

## Checks mapped to risks

- Natural boundary, branch-density, rejoin-cluster, oversized-cluster tests prove chunk policy.
- Linear, local rejoin, persistent, nested, cross-arm, conditional, and unresolved fixtures prove
  mechanics overlay and branch-lineage rejection without private hard-coding.
- Range/order and invented choice/arm cases prove mapper validation.
- Fake all-cloud, refusal/fallback enabled, refusal/fallback disabled, deliberate local-only, local
  unavailable/identity mismatch, timeout, rate limit, bad JSON, cancellation, and partial assembly
  cases prove execution policy.
- Exact-caption quotation, setup-control filtering, stable nested target, ambiguous cross-arm
  rejection, and transitive dependency/import tests prove the Python/AI and architecture
  boundaries.
- Relevant M10/M11/M12, ingestion, privacy/isolation, source-navigation, and package-import
  regressions protect lower-level authority.

## Explicitly not used

No Stage H or Stage E job, whole-scope hierarchy/editorial prompt, boundary vote, fine narrative
unit, atom membership, evidence-per-claim allocation, hierarchy compiler, semantic repair,
repair-lock protocol, old M15 publication path, or exact AI replay is called or adapted into this
pipeline. Historical code remains untouched and readable until Phase 05.
