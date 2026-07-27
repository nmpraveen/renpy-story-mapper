# **PHASE 04 LEAN DESIGN — FINISH THE STORY MAP, NOT A PLATFORM**

Date: 2026-07-26

Status: Supersedes the earlier production-grade Phase 04 design. Awaiting a fresh lightweight
semantic review.

## Product flow

```text
Ren'Py files
  -> existing Python chronology and branch mechanics
  -> coherent script chunks
  -> AI gives rough summaries
  -> Python restores exact known choices/routes/rejoins/state changes
  -> simple sections and whole-story overview
  -> existing local website
```

That is the product. Phase 04 does not need to prove that it is a general-purpose workflow engine,
high-availability service, formal verifier, or internet-scale graph system.

## Reuse the current implementation

At checkpoint `2995d99`, the branch already contains useful Phase 04 foundations:

- occurrence-aware full-game planning and coherent chunking;
- schema-v7 durable run/job/cache/generation storage;
- approved cloud mapping execution and Python validation/overlay;
- semantic events, section candidates, rollup types, and durable section jobs;
- scalable reader APIs and a lazy vertical story browser;
- workflow HTTP contracts/composition work; and
- repository-wide timing-balanced CI shards.

Do not rewrite or remove these foundations merely to make the architecture look simpler. Simplify
the remaining work: connect the pieces that are needed for one real end-to-end result and ignore
unused hardening.

## Remaining vertical seams to verify and finish

1. Accepted mapping results become story events.
2. Story events become simple chronological sections and one whole-game overview. If an AI rollup
   is unavailable, concatenate or lightly group existing accepted summaries instead of starting a
   repair architecture.
3. The completed structure is published as one readable generation that the existing reader can
   open.
4. The website advertises and invokes prepare, start, status, cancel, and resume through the
   existing service. Indeterminate-job retry may remain unavailable unless the real run needs it.
5. The website shows progress and then opens the same chronological story reader.

Before changing code, inspect the current implementation and remove any item above that already
works. Do not recreate it under a new name or schema.

## Two bounded implementation tasks

### Backend/API task

Own Python only:

- complete the existing run → summaries → sections/overview → publication path;
- compose the existing workflow service into the current web bootstrap/routes;
- use a deterministic structural fallback when summary/rollup prose is missing; and
- add only focused tests for the exact vertical path.

No new schema version, scheduler, protocol family, provider adapter, retry system, or generation
model is authorized without a reproduced blocker and user approval.

### Website task

Own current static website files and focused browser tests only:

- consume advertised existing workflow routes;
- show a compact preview and explicit consent action;
- show plain progress such as `12 of 18 chunks summarized`;
- support cancel/resume when advertised;
- open the existing whole-story reader when a generation is available; and
- preserve readable vertical chronology, nested local choices, alternative routes, rejoins, Path,
  and Detail/Evidence at normal desktop and 200% zoom.

Do not build a canvas, dashboard, generic graph engine, settings center, or new navigation level.

## Story and AI policy

- Existing Python authority remains the source of known chronology, choices, arm order,
  requirements/effects, destinations, routes, rejoins, endings, and source evidence.
- AI summarizes what happens. Approximate prose is acceptable; mechanics are overlaid from Python.
- Keep the existing product mapping configuration unless the user separately asks to reopen model
  selection. Codex implementation-agent settings are separate from the product's AI provider.
- No AI call occurs on import, open, prepare, status, or ordinary reading.
- A private run requires a fresh zero-submit preview and exact consent.
- A failed summary becomes a visible structural placeholder. Do not start iterative repair loops.

## Real-game acceptance

Run the current MsDenvers project as soon as the vertical path works. Inspect a small representative
sample:

- Day 1 chronology and its four choices;
- one later local choice and rejoin;
- one persistent character route;
- one state-dependent scene showing the important prerequisite/effect;
- one ending; and
- Path plus Detail/Evidence from visible story items.

The real question is: **Can the user quickly understand the story and how its important branches
work?** If yes, Phase 04 should move toward completion. Do not invent new acceptance work because
the output is not perfect.

## Deliberate non-goals

- exhaustive crash, lease, cancellation-timing, cursor-tamper, and cross-process matrices;
- theoretical extreme-scale thresholds or repeated memory benchmarking;
- perfect full-game summary coverage percentages;
- advanced `NEW` diff behavior or exhaustive stale-generation lifecycle;
- semantic reproducibility, formal evidence allocation, or exact AI prose replay;
- per-worker reviews or repeated full CI/Release runs; and
- Phase 05 cleanup, M14 tracing, installers, hosted service, or game modification.

Already-working versions of these features may remain. They are not a reason to spend more time.

## Quota and stop policy

- Use no more than two concurrent implementation tasks.
- For this resumption, dispatch workers/reviewers with `gpt-5.6-sol`, Medium reasoning, and fast
  mode disabled.
- Run affected tests while editing, one focused integrated gate after both tasks, sharded CI at the
  intended PR-candidate boundary, and one final Release/package gate.
- Do not keep the Orchestra active to watch healthy CI.
- Stop and ask before a new architecture layer, second correction loop, model change, unpreviewed
  private provider call, or scope expansion.
