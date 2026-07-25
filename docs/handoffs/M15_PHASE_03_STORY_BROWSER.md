# M15.1 Phase 03 — Whole-Story Synthesis and Path-Aware Browser

## How to use this file

Start one new user-visible Codex task in the Ren'Py Story Mapper repository and paste this entire
file as its instruction. That task is the **Phase 03 Coordinator**.

The coordinator owns the single Phase 03 goal, decisions, shared contracts, visible task creation,
integration, the one bounded private synthesis call, browser acceptance, Git, and final handoff.
It must coordinate the work; it must not quietly implement every track inside the coordinator task.

This file authorizes **Phase 03 only**. Do not start Phase 04, Phase 05, M14, full-game processing,
dynamic tracing, installer work, or legacy-code removal.

## Required starting state

Before writing code:

1. Read `.agents/skills/renpy-milestone/SKILL.md` completely and follow it.
2. Read `docs/MASTER_PLAN.md`, `docs/PROJECT_STATE.md`, the M15 milestone records, and this file.
3. Fetch GitHub and verify that local `main` is clean, current, and contains the accepted Phase 01
   and Phase 02 clean merge. Do not continue from the historical PR #26 branch.
4. Verify `src/renpy_story_mapper/story_map_v2/` and its focused tests exist on `main`.
5. Verify the accepted private Phase 02 artifact package exists locally and remains outside Git:

   `C:/Users/prave/Documents/Codex/Renpy/output/m15-story-map-v2-phase-02-20260724-2135/`

6. Verify `acceptance-summary.json` still reports a complete 1/1 core, 12 events, four story
   choices, eight branch outcomes, and zero validation failures. Verify the recorded protected
   source/archive/project fingerprints before using the package.
7. Create one Phase 03 branch from the updated `main`, normally
   `codex/m15-phase03-story-browser`. Open one Phase 03 PR only after integration verification; do
   not reuse or reopen PR #26.
8. Replace the completed Phase 02 repository contract with exactly one Phase 03 contract using the
   done condition below, then create exactly one native Phase 03 goal. Keep it active through
   implementation, integration, private acceptance, screenshots, final review, and PR readiness.

If the clean Phase 01/02 merge is absent or the private accepted core no longer matches its
recorded identity, stop and report that exact blocker. Do not reconstruct Phase 02 from historical
Stage H/E code.

## Product purpose

Build the product the user actually asked for: a simple private story guide.

The primary screen should answer two questions:

1. **What is the whole story?**
2. **What choices, requirements, and state changes create each branch?**

The reader should be able to understand Day 1 by scrolling normally. A path-to-target view is
useful, but it is a secondary action on a story item, not the dominant interface.

The product does not need publication-grade accuracy, reproducible AI wording, exhaustive line
ownership, atom IDs, claim IDs, or a formal proof for every summary sentence. Short approximate
story summaries are acceptable. Python remains authoritative for exact branching mechanics.

The intended division of labor is:

```text
accepted Phase 02 story-facing core
  → Terra groups the existing events and writes the whole-story overview
  → Python validates referenced anchors and overlays exact mechanics
  → normal-flow vertical browser renders broad sections and local branches
  → M12 supplies compact entry-to-target witness paths
  → existing source navigation opens Detail/Evidence
```

Do not revive Stage H, Stage E, adjacent-gap voting, fine atoms, hierarchy compilers, semantic
repair locks, or exact-prose replay under different names.

## Locked Phase 02 input

Phase 03 consumes rather than recreates the accepted Phase 02 core:

- one complete source-ordered core;
- one useful whole-scope title and overview from the mapper;
- 12 chronological narrative events;
- four exact story choices and eight unique branch outcomes;
- 12 event anchors and eight branch-outcome anchors;
- Python-owned exact captions, arm order, conditions, effects, destinations, rejoins,
  reachability, warnings, and source locations;
- one cloud execution record and unchanged protected inputs.

The accepted private files are:

- `story-map-v2-core.json` — machine-readable authority for Phase 03;
- `story-map-v2-core.md` — readable developer inspection;
- `acceptance-summary.json` — counts and protected-input record;
- `execution-ledger.json` — provider accounting and provenance.

Private source, derived private records, provider responses, screenshots, model evaluations, and
external Gemini/Grok material must remain outside Git. Tests and tracked fixtures must use small
synthetic stories with no private names or dialogue.

## Phase 03 done condition

Phase 03 is done only when the exact accepted Day 1 core opens through the supported local website
as a compact chronological story map with:

- one whole-story title and short overview when synthesis succeeds;
- five to seven broad chronological story sections when synthesis succeeds, or a complete readable
  chronological event view with no fixed section count when deterministic fallback is active;
- all 12 accepted narrative events represented once in source order;
- all four exact choices and all eight exact arms nested at the correct story location;
- exact conditions, effects, destinations, and four known rejoins supplied by Python;
- selectable events and branch outcomes with understandable entry-to-target witness paths;
- exact Detail/Evidence and source navigation from every visible event and arm;
- project reopen without repeating the accepted mapping or synthesis call;
- readable normal-flow HTML at 100% and 200% zoom with no horizontal page overflow;
- a provider-free fallback view when synthesis is absent or fails;
- final private screenshots approved by the user;
- independent exact-head review with no unresolved P0-P2;
- focused checks and the exact pushed PR-head GitHub checks passing;
- one Phase 03 PR ready and unmerged for explicit user approval.

Phase 03 does not require full-game scheduling, crash recovery, legacy migration, or packaging.

## Desired Day 1 presentation

The result should be close to this narrative shape. Exact section titles and grouping may vary if
the story remains clear and chronological.

```text
Day 1 — short whole-story overview
│
├── Introduction and household
│
├── Terrance's disciplinary meeting
│   ├── Fight with Max and breakup with Sandy
│   ├── Choice: tell him off / ignore him
│   ├── Rejoin
│   ├── Wanda attempts an emotional breakthrough
│   ├── Choice: address his behavior / change the subject
│   ├── Rejoin
│   └── Twice-weekly counseling arrangement
│
├── Janet's salary-cut meeting
│
├── Family dinner
│
├── Faye comforts Wanda and offers a massage
│   ├── Choice: end the massage / keep going
│   ├── If keep going: choice to stop Faye / let her continue
│   ├── Exact effects shown on the relevant arms
│   └── All outcomes rejoin at the Day 2 boundary
│
└── Day 2 transition
```

The page must not look like a generic engineering graph. Do not show repeated `START` cards, raw
anchor IDs, canonical node IDs, atom IDs, lifecycle states, provider jobs, or technical warnings
as primary story content.

## AI responsibility and synthesis contract

AI may do only the narrative-compression work it is good at:

- write or refine the whole-story title and overview;
- group existing Phase 02 events into five to seven broad chronological sections;
- write a short title and summary for each section;
- optionally describe one or two broad narrative threads using existing event anchors.

The synthesis request should contain only the story-facing Phase 02 core needed for those tasks:

- existing event anchors, titles, summaries, characters, and source order;
- existing branch-outcome anchors and summaries;
- compact Python-owned choice/arm mechanics needed to understand consequences;
- explicit instructions that all returned IDs must come from the request.

Do not resend the raw Ren'Py script when the accepted core already contains enough story context.
Do not send source paths if opaque stable anchors are sufficient. Never send the private oracle,
Phase 01 reference answer, Gemini/Grok answers or images, screenshots, old provider responses,
unrelated files, secrets, or game assets.

Use one small versioned response shape:

```text
story_title
story_overview
ordered_sections[]:
  section_title
  section_summary
  ordered existing event_anchor_ids[]
optional_threads[]:
  title
  summary
  ordered existing event_anchor_ids[]
```

Python validates only the useful structural facts:

- every referenced event anchor exists in the accepted core;
- no event anchor is duplicated;
- section and event order is chronological;
- every accepted event appears exactly once, or is placed into a deterministic chronological
  fallback section when omitted by AI;
- empty sections, unknown IDs, reverse ordering, and foreign IDs are rejected;
- AI text cannot alter choices, arms, requirements, effects, destinations, rejoins, reachability,
  source locations, or witness routes.

Do not require the model to retranscribe exact choice captions or mechanics. Python already has
them. Do not fail the whole map because punctuation or prose differs from another run.

If a valid synthesis omits an event, retain the useful synthesis and place that event into the
nearest deterministic chronological section with one visible warning. If the response is invalid
or unavailable, show the complete Phase 02 events in deterministic chronological groups instead
of hiding the map.

## Exact provider authorization for this phase

Pasting this handoff into a new task explicitly authorizes **one** private whole-story synthesis
submission after the zero-submit preview and provider-free gates below pass:

- provider/model: exact `gpt-5.6-terra`;
- reasoning: High;
- fast mode: off;
- planned and absolute cloud submissions: one;
- input: only the accepted story-facing Phase 02 core fields listed above;
- semantic retry: none;
- auditor: none;
- mapper rerun: none;
- local fallback: none.

The coordinator must produce and inspect a zero-submit preview binding the accepted core identity,
transmitted fields, payload hash, schema/prompt identity, exact provider settings, and one-call
ceiling. Starting this prompt is the user's consent for that exact bounded call, so do not pause
again merely to ask the same permission. Any model, scope, transmitted-field, retry, auditor, or
call-ceiling change requires new explicit user approval.

If Terra refuses, times out, fails transport, returns invalid output, or cannot be identity-
verified, record the failure and render the deterministic Phase 02 fallback. Do not call Sol,
Luna, local Qwen, or Terra again. Local Qwen has not been validated for whole-story synthesis.

## Python responsibility

Python owns only the facts it handles reliably:

- accepted event/branch anchor identity and chronological order;
- exact choice placement and nested choice ownership;
- exact arm captions and order;
- requirements, conditions, state/stat changes, and unresolved facts;
- destinations, local rejoins, persistent paths, loops, and endings;
- target reachability and M12 entry-to-target witness paths;
- source paths, physical line evidence, and Detail/Evidence links;
- stable storage and reopen of the accepted core and optional synthesis record.

Do not make Python decide whether two paragraphs are one human story event. Do not add a second
semantic boundary algorithm. Do not use exact AI prose as identity.

## Minimal project integration

Phase 03 may add the smallest project-bound storage and API seams needed to use the accepted core
through the website and reopen it later:

- store one current Story Map V2 core keyed to its source/authority identity;
- store zero or one validated synthesis result with provider provenance and input identity;
- reject stale records when the bound source/authority identity changes;
- load the deterministic fallback when synthesis is absent;
- expose read-only Story Map V2 and path/detail endpoints to the local browser.

Use existing project transaction and source-navigation primitives. Do not build a durable job
scheduler, retry queue, full-game cache, cross-process recovery engine, migration framework, or
multi-model lifecycle in this phase. Those belong to Phase 04.

## Browser behavior

Use semantic normal-flow HTML in a bounded readable column. Do not use a world canvas or force the
whole story to fit one viewport.

Required presentation rules:

- broad story sections are the primary cards;
- accepted events appear inside their section in chronological order;
- choices are nested locally where they occur;
- nested choices appear only inside the parent arm that reaches them;
- arms stack vertically when space is narrow or browser zoom is 200%;
- requirements and state changes use short readable badges;
- local rejoins use one compact connector or labeled continuation, not duplicated story cards;
- persistent branches remain visibly separate until a proven rejoin or ending;
- one continuation appears once after a rejoin;
- technical warnings are collapsed behind one optional **Analysis notes** control;
- unresolved behavior is one plain-language warning, not a wall of canonical-node messages;
- source and Detail/Evidence are secondary actions on the selected item;
- existing legacy maps may remain internally for compatibility, but Story Map V2 is the primary
  story page and the rejected wide semantic graph is not shown as the default product.

Required responsive behavior:

- no page-level horizontal scrollbar at 100% or 200%;
- no overlap, clipped text, microscopic fit-all scaling, or fixed-width branch sprawl;
- keyboard focus and selection remain visible;
- selecting a deep item does not permanently move the reader away from it;
- provide a small inline path panel, drawer, or return-to-selected action;
- preserve selected item and scroll context when Detail/Evidence is opened and closed.

Keep helper text minimal. Prefer plain story language over implementation terminology.

## Path and evidence behavior

Every visible accepted event and every exact arm should be selectable. Selection uses its existing
Phase 02 anchor. Python-owned destination/rejoin targets may also be selectable when an exact event
anchor does not exist; section headings do not invent new story targets. Bind the Day 2 boundary
case to the existing deterministic line-793 destination/rejoin target rather than inventing a Day
2 event anchor.

For a selected target:

1. Ask the current deterministic route authority/M12 solver for an entry-to-target witness.
2. Show the important choices, requirements, and state effects on that witness in story order.
3. Highlight the selected event or branch locally in the story map.
4. If the route is unresolved, show the known static prefix and a short honest explanation.
5. Link to exact Detail/Evidence and source locations already owned by deterministic authority.

At minimum, acceptance must prove these five target classes:

1. an early linear event;
2. an event after a local rejoin;
3. an event inside an alternate arm;
4. the deepest nested branch-specific outcome;
5. the Day 2/end boundary.

The preferred product supports all 12 events and all eight branch outcomes, not only the five
demonstrations.

## Required orchestration topology

The coordinator must use separate user-visible Codex tasks/worktrees for the three tracks below.
Use the Codex task-creation tool so they actually appear as separate tasks. Hidden subagents do not
replace these top-level track tasks.

```text
Phase 03 Coordinator — goal, decisions, shared seams, integration, provider call, Git
├── Track A Coordinator — synthesis contract, validation, minimal storage/API
│   ├── bounded workers if useful
│   └── independent exact-head reviewer
├── Track B Coordinator — compact vertical browser and responsive behavior
│   ├── bounded workers if useful
│   └── independent exact-head reviewer
├── Track C Coordinator — witness paths and Detail/Evidence navigation
│   ├── bounded workers if useful
│   └── independent exact-head reviewer
└── Final Cross-Track Reviewer — exact integrated head, private result, screenshots
```

Every visible milestone task must explicitly request `gpt-5.6-sol` with High reasoning and fast
mode disabled. If the task tool cannot set or verify fast mode, record that limitation honestly.
Do not claim repository prose changed the running model.

The coordinator should:

1. freeze the shared Story Map V2 browser/synthesis contract;
2. run the repository's one early semantic-review gate;
3. dispatch Track A first for shared records if necessary;
4. dispatch Tracks B and C in parallel once their shared seams are frozen;
5. require each track's independent reviewer to inspect its exact head;
6. integrate reviewed commits only;
7. run provider-free integration checks;
8. create the exact zero-submit synthesis preview;
9. spend the one authorized Terra call once;
10. run private browser/path acceptance and capture candidate-head screenshots;
11. send that exact integrated head, artifacts, and screenshots to the final cross-track reviewer;
12. correct and rereview any findings, then recapture screenshots if code, content, or rendering
    changed;
13. obtain explicit user visual approval of the actual final-head screenshots;
14. push one Phase 03 PR and wait for exact-head GitHub checks;
15. stop with the PR open and unmerged for explicit user merge approval.

The coordinator alone mutates the integration branch, performs the private provider call, updates
lifecycle authority, pushes GitHub, or changes PR state.

## Test and acceptance plan

Use generalized synthetic fixtures for tracked tests. At minimum cover:

- linear events grouped into broad sections;
- local choice with two arms and a proven rejoin;
- nested choice owned by only one parent arm;
- persistent branch without a rejoin;
- unresolved target and partial witness;
- unknown, duplicate, omitted, and reverse-ordered synthesis anchors;
- synthesis unavailable with complete deterministic fallback;
- stale stored core/synthesis identity after source change;
- reopen without another provider construction;
- exact Detail/Evidence navigation for events and arms;
- 100% and 200% normal-flow rendering with no horizontal overflow.

Before the live call, run focused Story Map V2, synthesis validation, storage/API, browser, route,
source-navigation, privacy, import-isolation, Ruff, strict mypy, JavaScript syntax, JSON/schema,
and whitespace checks. Do not rerun unrelated expensive suites locally merely for ceremony; the
exact pushed PR-head workflow remains the repository-wide release gate.

Private acceptance must record:

- exact accepted-core and protected-input identities before and after;
- preview and transmitted-field hashes;
- exact provider settings and one-call accounting;
- synthesis result or honest deterministic fallback;
- section/event/choice/arm/rejoin counts;
- five path-class results and source-navigation results;
- project reopen with zero new provider calls;
- screenshots of overview and a selected deep path at 100% and 200%;
- no remote asset request from the local browser;
- final reviewer verdict and exact PR-head checks.

## Acceptance criteria

Phase 03 passes only when:

1. It starts from the merged clean Phase 01/02 `main`, not the historical PR #26 branch.
2. One active Phase 03 contract and one native goal own exactly this phase.
3. The one early semantic review passes before broad implementation.
4. Separate visible Track A/B/C tasks/worktrees and independent reviewers are actually used.
5. AI performs only broad narrative synthesis over existing accepted anchors.
6. Python alone owns exact mechanics, chronology, routes, reachability, and source navigation.
7. Successful synthesis has five to seven readable chronological sections and represents all 12
   accepted events once; deterministic fallback represents all 12 once in a complete readable
   chronological view without a fixed section-count requirement.
8. All four exact choices/eight arms and all known rejoins appear in the correct local context.
9. Every event and arm reaches exact Detail/Evidence; path witnesses are proven for the five
   required target classes.
10. The deterministic fallback remains complete and usable without successful synthesis.
11. The one Terra/High/fast-off call is preview-bound, exactly accounted, and never retried or
    substituted.
12. Reopen uses the stored accepted records and adds zero provider calls.
13. The page is readable at 100% and 200% with no horizontal overflow, overlap, or fit-all shrink.
14. Private source, outputs, responses, and screenshots stay outside Git; protected inputs remain
    unchanged and no game/Ren'Py/creator code runs.
15. The user approves final-head screenshots.
16. Independent final review reports no unresolved P0-P2 and exact pushed-head checks pass.
17. Lifecycle evidence and direct local artifact links are complete; the Phase 03 PR remains open
    and unmerged for explicit user approval.
18. Phase 04/05, M14, full-game scaling, legacy retirement, installer work, and dynamic tracing do
    not begin.

## Stop rules

- If a design introduces another semantic hierarchy/compiler/repair system, stop and simplify.
- If AI grouping is useful but misses an event, preserve it and use deterministic fallback
  placement; do not rerun merely to improve prose.
- If exact provider identity or the preview-bound payload cannot be verified, do not submit.
- If the one Terra call fails, do not retry or substitute another model.
- If a path cannot be proven, show it unresolved; do not let AI invent connectivity.
- If exact mechanics disagree with AI prose, retain the prose only where harmless and display the
  Python mechanics as authority.
- If private input fingerprints change, stop immediately.
- If the browser only works as a wide canvas or unreadable graph, Phase 03 fails.
- If the old Stage H/E product becomes a dependency of the supported Story Map V2 path, Phase 03
  fails.

## Later phases — titles only

- **Phase 04 — Full-Game Scaling, Persistence, and Recovery**
- **Phase 05 — Legacy Workflow Retirement and Final Product Acceptance**
