# M15.1 Story Map V2 — Phase 02 Core Rewrite Coordinator Prompt

## How to use this file

Start one new user-visible Codex task in the Ren'Py Story Mapper repository and paste this entire
file as its instruction. That task is the **Phase 02 Coordinator**. It owns the goal, the one active
M15.1 contract, task creation, decisions, integration, live acceptance, Git, and the final handoff.

This file authorizes **Phase 02 only**. Do not begin Phase 03's final whole-story synthesis/browser
experience, Phase 04's full-game scaling and recovery work, Phase 05's legacy retirement, M14, or a
new milestone. Do not merge PR #26.

## User-approved product direction

Build a practical private story guide, not a publication-grade narrative compiler.

The eventual product must let a user:

1. Read a concise chronological overview of the supplied story.
2. See important choices, branch outcomes, requirements, state/stat changes, rejoins, persistent
   routes, and endings in the correct story location.
3. Select a meaningful event and see an understandable route from story entry to it.
4. Open the exact source later when more detail is needed.

Approximate AI wording and grouping are acceptable. The product does not require reproducible AI
prose, one-to-one line ownership, claim-level evidence allocation, exhaustive atom IDs, or formal
proof of every sentence. Static Ren'Py analysis remains authoritative for path-critical mechanics.

The desired workflow is intentionally simple:

```text
read-only Ren'Py source
  → coherent script chunks
  → AI summarizes story/events/branch outcomes
  → Python overlays and checks exact mechanics
  → one chronological Story Map V2 core record
```

Do not revive Stage H, Stage E, adjacent-gap voting, hierarchy membership compilation, or the
fine-atom/evidence architecture under new names.

## Phase 01 decisions that are now locked

Phase 01 and its local-model supplement are complete and accepted as the basis for Phase 02.

- The compact vertical concept worked and is the visual/product direction.
- Default chunk mapper: `gpt-5.6-luna`, High reasoning, fast mode off.
- Later whole-story synthesizer: `gpt-5.6-terra`, High reasoning, fast mode off.
- Default auditor: none. The tested audit stage added no corrective value.
- Initial production chunk target: one coherent scene/day corridor around 8,000 raw-story tokens,
  with earlier splitting near 5,000 for branch-heavy material and a validated ceiling near 10,700.
- The Phase 01 report's conservative 2,500-token Luna default is not a proven context limit. Its
  four sizes contained different story material, each cell was sampled once, Luna's 5.3k result was
  semantically strong but operationally quarantined, and Luna passed the complete 10.7k Day 1.
  Do not turn that conservative report rule into dozens of tiny production calls.
- Prefer natural story boundaries over a numeric target. Keep a menu, its arms, and its nearby
  rejoin together whenever the complete corridor fits below the validated ceiling.
- Sol remains the quality reference, not the routine production default. Terra was the strongest
  observed quality/speed balance at full Day 1, but exact end-to-end prices are unavailable. Keep
  Luna as the initial low-cost mapper and measure the actual Phase 02 workflow before claiming the
  cheapest complete pipeline. A later user decision may promote Terra if Luna's real output or
  total-call economics are worse.
- No default auditor is a simplicity decision, not proof that auditing can never help. Phase 01
  tested only a clean candidate. Phase 02 must not add an always-on auditor; a later selective
  review can be reconsidered only if real invalid outputs justify it.
- Hosted models processed the Day 1 sexual material without a content refusal. The two recorded
  hosted `policy_violation` cells were experiment-integrity quarantines, not content-policy blocks.

Local backup decision:

- Keep cloud processing as the default.
- Support the already-tested LM Studio model
  `qwen3.5-35b-a3b-uncensored-hauhaucs-aggressive` as an optional private mapper fallback.
- Local fallback is used only when the cloud provider explicitly refuses a particular chunk for
  content/safety reasons, or when the user deliberately selects local/private processing.
- Never pre-classify sexual content with keyword filters or another model.
- Never silently switch providers unless the user enabled local fallback in the exact run preview.
- For a refused cloud chunk, reuse the exact same packet boundaries locally.
- For a deliberate local-only run, target about 8,000 raw-story tokens, split branch-heavy material
  nearer 5,000, and treat about 10,700 as the currently validated maximum.
- Local Qwen is validated only for chunk/story mapping. It is not yet approved as the whole-story
  synthesizer.

Phase 01 evidence is local at:

`C:/Users/prave/Documents/Codex/Renpy/output/m15-story-map-v2-phase-01-20260724-154950/`

Important evidence includes `PHASE_01_REPORT.md`, `MODEL_CONTEXT_MATRIX.csv`,
`final-review-rereview/FINAL_REREVIEW.md`, `prototype/PROTOTYPE_HANDOFF.md`, the four screenshots,
and `lm-studio-supplement/REPORT.md`.

## Phase 02 objective

Implement and prove the new **Story Map V2 core pipeline** on the extracted private Day 1 project.

Phase 02 ends with a validated, provider-generated, machine-readable core record that contains:

- source-ordered story chunks;
- meaningful events with concise titles and summaries;
- branch-outcome summaries;
- exact Python-owned choices, arm order, conditions, effects, rejoins, and destinations;
- a stable target anchor and reachability status for every visible event and branch-specific event;
- clear unresolved warnings where static analysis cannot prove behavior;
- simple provider provenance and partial/failure status.

Phase 02 does not need to ship the final browser experience. It may produce a very small developer
preview for inspection, but the supported compact vertical browser, final Terra synthesis, and
interactive path highlighting belong to Phase 03.

## Core architecture

Create a clean package/seam for Story Map V2 rather than extending the rejected semantic stack.
Prefer a new bounded package such as `src/renpy_story_mapper/story_map_v2/` with focused tests.
Exact names may change during the early semantic review, but the responsibilities must remain
simple and separate:

1. **Source/mechanics adapter** — reads current read-only project authority and emits only source
   ranges plus useful mechanics: labels, menus, exact arm captions/order, conditions, assignments,
   jumps/calls/returns, proven rejoins/destinations, reachability, and unresolved behavior.
2. **Chunk planner** — partitions a chosen chapter/day/scope in source order at natural boundaries,
   normally around 8k raw-story tokens, without cutting through a menu/arms/rejoin cluster.
3. **Mapper request/response** — sends one coherent line-numbered chunk plus its compact mechanics
   digest and receives rough story sections, events, source ranges, and branch-outcome summaries.
4. **Validator/overlay** — validates only small structural facts and overlays exact mechanics from
   Python. AI text is never authority for exact captions, arm order, conditions, effects, rejoins,
   destinations, or reachability.
5. **Core assembler** — combines accepted chunks in chronological order and exposes stable target
   anchors for Phase 03.
6. **Provider policy** — cloud Luna by default; optional LM Studio fallback only under the locked
   refusal/manual rules above.

Do not make AI retranscribe exact mechanics. Internally, branch summaries may reference a compact
mechanical key such as source choice line plus arm order. Python resolves that key and inserts the
exact caption/mechanics. These keys stay out of the normal user-facing story map.

The AI transport schema should stay small. A suitable shape is conceptually:

```text
scope title + scope overview
ordered events: title, summary, valid source range, characters, optional warning
ordered branch summaries: existing choice key, existing arm order, outcome summary
```

Do not add atom membership, evidence IDs per sentence, exact line coverage, graph coordinates,
stable AI wording hashes, hierarchy levels, claim objects, or repair-lock protocols.

## Provider and fallback behavior

### Cloud primary

- Use exact `gpt-5.6-luna`, High reasoning, fast mode off for Phase 02 mapping.
- Do not silently substitute Terra, Sol, another reasoning level, or fast mode.
- If identity/settings cannot be verified, stop before transmitting private text.
- Do not add a default AI auditor.
- Phase 03, not Phase 02, will integrate the Terra whole-story synthesis call.

### Local fallback

Expose one per-run option in the prepared manifest:

`Allow local fallback when cloud refuses a chunk`

When enabled, an explicit hosted content/safety refusal may send the identical refused chunk and
schema to the configured loopback LM Studio mapper. Record that section as `local_fallback`.

Do not fall back locally for timeouts, rate limits, authentication failures, invalid JSON, ordinary
quality issues, provider identity mismatch, or user cancellation. Those conditions remain honest
errors/retry decisions. Never enter a cloud/local retry loop and never rewrite/censor source text to
evade a provider restriction.

Do not download a model, start LM Studio, or load/unload a model automatically. Detect the existing
loopback service and exact loaded model using reusable safe code where available. If the local model
is unavailable, preserve the deterministic mechanics and mark only the missing narrative summary
as unavailable.

Do not send locally generated summaries back to a cloud synthesizer unless a later run preview
explicitly lists that transmission and the user consents.

Keep status simple:

- run summary: `Cloud N · Local fallback N · Missing N`;
- affected section badge: `Local fallback`;
- refusal message: `Cloud declined this section. Local fallback is available.`

## Live-provider authorization and ceiling

The user's instruction authorizes one exact private Day 1 Phase 02 acceptance run through the new
cloud-primary mapper after a zero-submit preview confirms source identity, exact model/settings,
packet count, transmitted fields, and limits.

- Maximum planned hosted submissions: six Luna mapper calls.
- Maximum hosted submissions including confirmed no-response transport replacements: eight.
- No semantic retry and no default auditor call.
- Do not call Terra or Sol in Phase 02 live acceptance.
- A local submission is permitted only for an actual hosted content/safety refusal when the run
  preview enabled local fallback and the exact local model is already available, or for a separate
  user-selected local-only run. Do not start a local-only validation run merely to spend the option;
  Phase 01 already supplies real local evidence.
- If safe coherent chunking needs more than six planned hosted calls, stop at preview and request a
  revised ceiling instead of silently shrinking context or submitting.

The preview must exclude the private evaluation sheet, external AI answers/images, old provider
responses, screenshots, unrelated files, secrets, and game assets. Never execute Ren'Py, game
Python, creator code, or the game executable.

## Required user-visible task topology

The coordinator must use Codex task/thread creation tools so the tasks actually appear in the
sidebar. Do not substitute hidden subagents for these requested tasks. Every current milestone task
must explicitly request `gpt-5.6-sol`, High reasoning, and fast mode disabled. If the task-creation
surface exposes no fast-mode selector, record that limitation rather than claiming it was set.

Create only dependency-ready tasks and keep at most the useful concurrency supported by the app:

```text
Phase 02 Coordinator — owns goal, contract, decisions, integration, consent, Git, and final report
│
├── Early Contract Reviewer — separate visible read-only task
│   └── reviews the simple V2 contract before broad implementation
│
├── Track A Coordinator — separate visible task/worktree
│   ├── Worker A1: source/mechanics adapter + chunk planner
│   ├── Worker A2: mapper schema + validator/overlay + core assembler
│   └── Track A exact-head reviewer
│
├── Track B Coordinator — separate visible task/worktree
│   ├── Worker B1: cloud provider preview/execution boundary
│   ├── Worker B2: refusal classification + opt-in LM Studio fallback
│   └── Track B exact-head reviewer
│
└── Final Integration Reviewer — separate visible read-only task
    └── audits the integrated exact head and private Day 1 acceptance artifacts
```

Track coordinators may create their workers only after the coordinator freezes shared seams. They
must use separate bounded branches/worktrees based on the exact integration head. They return
reviewed commits; only the Phase 02 Coordinator integrates them. Avoid parallel edits to the same
files.

Use bounded `wait_threads` snapshots for monitoring. Do not repeatedly open completed histories or
leave the user without a concise progress update for long-running work.

## Repository, lifecycle, and Git rules

- Milestone remains M15.1 inside M15.
- Integration branch remains `codex/m15-msday1-narrative-map`.
- Existing PR remains #26. Do not create a second M15 PR.
- PR #26 is not ready to merge and should remain draft/unmerged while the rewrite is incomplete.
- The local integration branch contains substantial rejected Stage H/Stage E history not yet on the
  remote. Do not push that stack at Phase 02 startup merely to synchronize it.
- Do not reset, rebase, force-push, squash away, or delete historical work. Historical data must
  remain readable until Phase 05 makes the compatibility decision.
- New V2 code must not import the rejected Stage H/E pipeline as its architecture. Reuse only
  genuinely useful lower-level ingestion, parser, M10/M11 mechanics, route solver, provider
  isolation, privacy, cancellation, and source-navigation seams.
- Keep exactly one active milestone contract and one native Codex goal through Phase 02.
- GitHub updates go through the existing PR branch, never directly to `main`.
- Do not push Phase 02 until integrated checks, private acceptance, and final exact-head review pass.
  A Phase 02 push is an intermediate checkpoint, not permission to mark the PR ready or merge it.

## Detailed workflow

### Step 0 — Preflight and one active goal

1. Read `AGENTS.md`, `docs/MASTER_PLAN.md`, `docs/PROJECT_STATE.md`, and all current M15 milestone
   files completely. Use the repository `renpy-milestone` skill.
2. Verify the exact integration worktree/branch, clean status, local/remote divergence, PR #26
   identity/state, and Phase 01 artifact hashes.
3. Verify the source/archive fingerprints still match Phase 01 before opening private inputs.
4. Inspect the current native goal. Create or update one goal for Phase 02 implementation only;
   do not create competing goals.
5. Update the active M15.1 contract to the exact Phase 02 objective, deliverables, exclusions,
   acceptance evidence, task topology, cloud/local policy, and provider ceilings in this file.

Stop on a material mismatch. Do not solve a dirty/misaligned worktree with reset or force operations.

### Step 1 — Early semantic/architecture review

Before broad code changes, freeze a short design note covering:

- the new V2 module boundary;
- exact lower-level authority reused from current parsing/M10/M11/M12;
- chunk input and mapper output shapes;
- Python-owned mechanics overlay;
- partial/failure behavior;
- provider/fallback state transitions;
- what old Stage H/E code is explicitly not used.

Create the Early Contract Reviewer task. It must reject any design that recreates atom allocation,
AI topology authority, exact prose replay, or multi-stage repair machinery. Broad implementation
starts only after the reviewer returns `PASS`. Apply at most one bounded correction and rereview;
if the simple contract still cannot pass, stop for user direction rather than iterating architecture.

Record the semantic gate in M15 lifecycle documents.

### Step 2 — Freeze shared contracts with failing-first tests

Write small versioned contracts and failing-first tests for:

- coherent chunk boundaries and limits;
- one simple mapper request/response;
- ordered event ranges;
- branch summaries referencing only real choice/arm keys;
- deterministic mechanics overlay;
- partial chunk status;
- cloud/local/missing provenance;
- stable event target anchors;
- no Stage H/E dependency in the supported V2 path.

Use synthetic generalized fixtures first: linear story, local rejoin, persistent split, nested menu,
conditional arm, unresolved dynamic target, long linear scope, and a refusal/fallback case. Do not
encode MsDay1 names, exact counts, or private wording into generic product tests.

Freeze Track A/Track B seam ownership before parallel dispatch.

### Step 3 — Track A: source, chunking, mapping, and assembly

Implement the smallest complete provider-neutral core:

1. Adapt current source and static mechanics into one compact ordered scope model.
2. Partition the scope near the configured raw-token target.
3. Never split inside a menu/arm body or before its locally proven rejoin when that cluster fits
   under the validated ceiling.
4. Permit an oversized coherent chunk only up to the configured validated maximum.
5. Record simple density metrics—menus, arms, conditions, transfers, unresolved items—to allow
   branch-heavy scopes to split earlier.
6. Serialize one line-numbered raw chunk and compact mechanics digest without atoms/evidence IDs.
7. Validate AI event ranges as ordered and inside the chunk. Reject invented choice/arm keys.
8. Overlay exact captions, order, conditions, effects, rejoins, destinations, and reachability from
   Python. Ignore AI punctuation or rewording for these exact fields.
9. Assemble accepted chunks by source order. Do not require identical AI wording on replay.
10. Give every visible event/branch-specific event a stable target locator derived from current
    authority plus source location—not from the generated title text.
11. Preserve honest unresolved markers without blocking unrelated story summaries.

If an AI chunk is missing or invalid, keep other accepted chunks and deterministic mechanics. The
core record becomes `partial`; do not manufacture a generic story summary or discard the build.

### Step 4 — Track B: cloud execution and local refusal fallback

Implement the smallest safe execution policy around the frozen contracts:

1. Zero-submit preparation returns source identity, exact packet list, raw/serialized sizes, fields
   transmitted, requested provider identity/settings, per-provider call ceilings, fallback option,
   and privacy exclusions.
2. Confirmation binds that exact preview. Changed source, packet plan, prompt/schema, provider,
   settings, or fallback option requires a new preview/confirmation.
3. Construct the provider lazily only after confirmation and immediately before submission.
4. Classify explicit content/safety refusal separately from timeout, rate limit, authentication,
   transport, schema, cancellation, and identity failure.
5. When and only when enabled, route the identical refused packet to the exact configured LM Studio
   mapper on loopback. Reuse existing safe loopback discovery where practical.
6. Do not automate model installation, download, server startup, loading, or provider cascades.
7. Record requested/resolved provider, cloud/local origin, usage where available, elapsed time,
   response hash, sanitized terminal reason, and packet status.
8. Cancellation stops future submissions and asks the active provider to cancel; completed chunks
   remain inspectable.

Phase 04 owns robust cross-process recovery and full-game durable scheduling. Phase 02 needs clean
in-process behavior and a minimal persisted acceptance artifact only; do not rebuild the old durable
semantic lifecycle.

### Step 5 — Integrate and run provider-free verification

The Phase 02 Coordinator integrates only reviewed Track A and Track B commits into the integration
worktree. Resolve seam mismatches centrally; do not ask tracks to edit each other's ownership.

Run focused tests plus the smallest relevant existing regression set for ingestion, M10/M11/M12
authority, provider privacy/isolation, source navigation, and package import. Add an explicit import
or dependency check proving the supported V2 core does not call Stage H/E.

Use fake providers to prove at minimum:

- all-cloud success;
- explicit cloud refusal + enabled local fallback + combined core record;
- explicit cloud refusal + fallback disabled;
- explicit cloud refusal + local unavailable/identity mismatch;
- timeout/rate limit/bad JSON does not trigger local fallback;
- one partial chunk does not erase other summaries or exact mechanics;
- cancellation prevents later submissions;
- exact captions/order/effects/rejoins always come from Python;
- local quotation marks around captions cannot corrupt exact mechanics;
- hint/setup controls are not promoted to story paths without deterministic route authority.

Do not run the full repository suite repeatedly. Run focused gates during development and one
broader Windows/package gate only when required by the phase contract.

### Step 6 — Private Day 1 acceptance

After provider-free integration and review:

1. Copy the exact private Day 1 project to a new local acceptance directory if current workflow
   requires writable project state. Keep original source/archive read-only.
2. Record pre-run hashes, sizes, and timestamps.
3. Prepare the exact zero-submit run manifest. Confirm no more than six planned Luna submissions,
   exact High/fast-off settings, transmitted fields, and local-fallback choice.
4. Execute once through the new supported core workflow.
5. Do not retry a semantic response. Use a replacement only for a confirmed no-response transport
   failure and remain under the eight-submission ceiling.
6. If a real content refusal occurs and fallback was enabled, use the identical packet locally only
   when the exact tested model is already available. Otherwise preserve a partial result and report
   what the user would need to start/load manually.
7. Recompute source/archive fingerprints and prove no game/creator code executed.

Inspect the resulting core record as a human. It must be recognizably the same Day 1 story shown in
the accepted prototype: introduction/household, Terrance, financial blow, dinner, Faye/massage, and
Day 2 transition, with the four story choices/eight arms and known rejoins mechanically correct.
Those private specifics are acceptance evidence, not hard-coded product rules.

Phase 02 does not require final visual approval. Provide a readable Markdown or minimal local HTML
dump solely so the user can inspect whether the core data is good enough for Phase 03.

### Step 7 — Independent exact-head review

Freeze the integrated head and acceptance artifacts, then create the Final Integration Reviewer.
It must inspect:

- contract simplicity and absence of rejected Stage H/E architecture;
- generalized tests versus private hard-coding;
- chunk boundary behavior and context ceilings;
- AI/Python responsibility separation;
- exact mechanics overlay and target anchors;
- cloud identity/settings and call accounting;
- refusal-only, opt-in local fallback;
- no silent retry/cascade/censorship behavior;
- source/archive immutability and private-data containment;
- focused regression results;
- actual private Day 1 core output readability.

No unresolved P0-P2 may remain. Fix only bounded findings, rerun affected checks, and obtain one
provider-free rereview. Do not make new live story calls merely to improve prose.

### Step 8 — Phase 02 handoff, Git, and stop

Create a concise Phase 02 report with:

- what the new core does in plain language;
- actual Day 1 chunk count and provider usage;
- cloud/local/missing section counts;
- the generated core record and readable preview;
- limitations deferred to Phase 03/04/05;
- exact commands/checks and final-review verdict;
- source/privacy/fingerprint result;
- integration commit and PR state.

Update all linked M15 lifecycle documents before the final implementation commit. If the integrated
exact head passes and contains no private artifact, push the existing integration branch to update
PR #26 and verify its exact-head GitHub checks. Keep the PR draft and unmerged because later phases
remain. Do not open another PR.

Complete the Phase 02 native goal only when every Phase 02 acceptance criterion is satisfied and no
required work remains. Then stop. Produce the Phase 03 prompt only after the user reviews the Phase
02 Day 1 core output.

## Phase 02 acceptance criteria

Phase 02 passes only when:

1. One active M15.1 contract and native goal describe this Phase 02 rewrite.
2. The early semantic reviewer passes the simple V2 design before broad implementation.
3. The supported V2 path does not depend on Stage H/E, adjacent-gap voting, atom allocation,
   hierarchy compilation, or exact AI prose replay.
4. Coherent chunks use natural story boundaries, normally target ~8k raw-story tokens, split
   branch-heavy material nearer ~5k, preserve menu/arms/rejoin clusters, and never exceed the
   ~10.7k validated ceiling in the private acceptance run.
5. The AI writes rough narrative meaning and branch outcomes; Python alone owns exact path-critical
   mechanics and reachability.
6. Generic tests cover linear, rejoin, persistent, nested, conditional, unresolved, oversized, and
   refusal/fallback cases without private story hard-coding.
7. Cloud mapping resolves exact Luna/High/fast-off identity with no silent substitution.
8. Local fallback is opt-in, refusal-only, loopback-only, same-packet, exact-model bound, visibly
   labeled, and never used for unrelated provider failures.
9. Missing/invalid summaries produce an honest partial core record while preserving completed
   chunks and deterministic mechanics.
10. The private Day 1 run stays within six planned/eight absolute hosted submissions, uses no
    semantic retry/default auditor, and records complete accounting.
11. The private core record is chronological and recognizably covers the major Day 1 story; all four
    story choices, eight exact arms, relevant effects, and known rejoins are mechanically correct.
12. Every visible event and branch-specific event has a stable target anchor and honest
    reachable/unresolved status for Phase 03.
13. Source/archive bytes, hashes, and timestamps remain unchanged; no game/Ren'Py/creator code runs;
    private packets/responses/acceptance output stay outside Git.
14. Focused regression tests pass and the independent exact-head reviewer reports no P0-P2.
15. Lifecycle docs, implementation commit, existing draft PR #26 checkpoint, and direct local
    artifact links are complete; PR #26 remains unmerged.
16. No Phase 03 browser/synthesis, Phase 04 scaling/recovery, Phase 05 retirement, M14, new PR, or
    false M15.1 completion occurs.

## Stop rules

- If the early design needs the rejected hierarchy/atom machinery, stop and simplify once; then ask
  the user rather than building it.
- If chunk summaries are useful but path facts disagree, keep the summaries and fix only the
  deterministic overlay. Do not give AI topology authority.
- If six planned hosted calls are insufficient, stop at preview for a new ceiling.
- If exact provider identity/reasoning/fast mode or private scope cannot be verified, do not submit.
- If cloud refuses content and local fallback was not enabled or is unavailable, return a partial
  map and a simple actionable message. Do not evade the refusal.
- If local output fails, preserve deterministic structure and mark only that summary missing.
- If source/archive fingerprints change, stop immediately.
- If a task proposes repeated semantic retries, auditor loops, prompt-version cascades, or exact
  prose reproducibility, reject that design as out of scope.
- If the new core is not materially simpler than Stage H/E, Phase 02 fails.

## Later phases — not authorized here

- **Phase 03 — Whole-Story Synthesis and Path-Aware Browser Experience**
- **Phase 04 — Full-Game Scaling, Persistence, and Recovery**
- **Phase 05 — Legacy Workflow Retirement, Final Acceptance, and PR #26 Readiness**
