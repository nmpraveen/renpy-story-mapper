# M15.1 Phase 04 implementation design

Date: 2026-07-26

Status: Approved product design; implementation remains gated by `SEMANTIC_REVIEW.md`.

## Product flow

```text
read-only Ren'Py inputs plus M10/M11/M12 authority
  -> occurrence-aware spine and persistent-route scopes
  -> frozen coherent script packets
  -> zero-submit preview and one exact approval
  -> six independent durable Terra mapping jobs
  -> Python validation and exact-mechanics overlay
  -> selective one-call Terra review or refusal-only loopback fallback
  -> fixed-membership meaningful sections and bounded overview rollups
  -> progressive immutable generation plus exact locator index
  -> whole-game manifest and lazy section/branch/path/detail browser
```

AI summarizes story meaning. Python owns placement, topology, mechanics, coverage, validation,
publication identity, navigation, recovery, and version comparison.

## Locked operating policy

- Product mapping and rollup model: `gpt-5.6-terra`, High, fast mode off.
- Six global independent submission slots; never batch or adapt worker count.
- Chunk profile: 8,000 normal target, 5,000 branch-heavy target, 10,700 hard maximum.
- One frozen approval covers unchanged pending work and explicitly disclosed loopback fallback.
- One cloud mapper call per job; one flagged cloud replacement review at most; one local mapper call
  only after explicit cloud content refusal. No iterative semantic repair.
- Definite non-transmission stays resumable; uncertain transmission is terminal-indeterminate until
  explicit job-specific retry approval.
- A final full-game generation may retain at most two noncritical placeholders and at most 5% of raw
  story tokens, never on choices/routes/rejoins/endings/new branches.

## Authority and packet shape

`StoryPlan` contains ordered `StoryScopeDescriptor` and `StoryPlacement` records. M11 hierarchy and
call occurrences establish narrative placement; M10 supplies exact path mechanics; source
path/line is a locator/tie-breaker. Persistent lanes are child scopes of their exact split rather
than sequential spine content. Shared called labels create occurrence-specific placements. Loops
are represented once with explicit repeatability.

`StoryChunkPlan` freezes scope, ordinal, placement coverage, profile, rendered-input identity, and
mechanics identity. Long persistent lanes chunk independently. An oversized local choice is split
at exact arm/scene boundaries with compact repeated parent mechanics and one Python-owned parent.
Raw packet text is reconstructed only while an active job needs it.

Mapper output remains compact: chunk title/overview, ordered events with approximate source ranges
and characters, and branch summaries referencing supplied choice/arm identities. Python rejects
foreign/missing/reordered/range-invalid mechanics, large unexplained coverage gaps, and wrong route
ownership, then overwrites all path-critical facts.

## Durable execution and publication

Schema v7 adds indexed V2 runs, jobs, attempts, cache, generations, section pages, selection
locators, and semantic view state. A lease/CAS claim limits execution to six independent workers.
An attempt reservation is durable before possible transmission. Result/cache/artifact/accounting
finalization is transactional. Crashed submitting attempts become `indeterminate`; completed work
and immutable normalized cache entries survive reopen.

The first run exposes an `active_build_generation` structural skeleton. Updated projects retain a
`current_complete_generation` while the candidate builds. Final publication atomically advances
the complete pointer. Read/status/open never constructs a provider. Source refresh stops stale work
and never mixes generations.

Terra sectioning receives only existing ordered event summaries inside one deterministic corridor
and returns prose plus contiguous first/last event references. Python proves exactly-once ordered
membership and route ownership. Whole-game synthesis receives verified section/route summaries;
large inputs use fixed-membership consecutive reduction. Invalid rollups use deterministic
headings/child summaries without repair.

## Scalable reader

The manifest is always small and complete: revision, overview, route/ending landmarks, ordered
section descriptors, counts, and build/coverage state. Section pages are capped at 30 events, 240
rendered items, and 1 MiB. Oversized branch children use branch cursors. Search and selection
locators cover unloaded content. All cursors bind revision, identity, order, offset, and limits.

The browser preserves the Phase 03 compact vertical visual grammar. It hydrates one section/window,
prefetches a neighbor, caps live story items at 600, and restores semantic selection/focus/viewport
across Detail and reopen. `NEW` is computed from deterministic new branch/route/ending facts against
the immediately previous accepted generation and lasts until the next generation; a toggle only
hides its labels.

## Integration waves

1. Track A occurrence-aware plan/chunking and Track B persistence/execution run concurrently after
   semantic `PASS`.
2. Integrate and freeze their contracts.
3. Track C assembly/API and Track D website/acceptance run concurrently against frozen fixtures.
4. Integrate reviewed heads, run final cross-track review, synthetic scale gate, real private run,
   user screenshot approval, exact-head Release/package gate, and prepare the unmerged PR.
