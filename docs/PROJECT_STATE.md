# Ren'Py Story Mapper project state

Updated: 2026-08-01

## Active work

- Active milestone: M15.2 Phase 06 Story River reader.
- Contract: [`docs/milestones/M15_PHASE_06/GOAL.md`](milestones/M15_PHASE_06/GOAL.md).
- Task ledger: [`docs/milestones/M15_PHASE_06/TASKS.md`](milestones/M15_PHASE_06/TASKS.md).
- Implementation roadmap: [`docs/milestones/M15_PHASE_06/IMPLEMENTATION_PLAN.md`](milestones/M15_PHASE_06/IMPLEMENTATION_PLAN.md).
- Active checkout: `codex/m15-phase06-story-river`, created from the completed Phase 05 reader at
  `46763c4` on 2026-07-31.
- Status: Phase 05 is the accepted factual and language baseline. The mock-fidelity Story River
  redesign is integrated and passes focused static checks. The focused 1920px/1280px browser proof
  is ready for user review; whole-game work remains gated on visual acceptance.
- Native Codex goal: none.

## Current product decision

Present the established Python-owned story as a vertically unbounded Story River. Shared chronology
uses a neutral main stream; each fork receives local route colors and stable visible codes; owned
events remain on their route until a proven rejoin or terminal; and an automatic panel explains the
route currently selected or passing through the reading position. This is an HTML scrolling reader,
not a pan-and-zoom canvas.

The first Phase 06 build retained the correct fitting-room route ownership and navigation, but the
user rejected its appearance on 2026-07-31: it was still the Phase 05 family tree with route colors,
not the selected Story River mock. The active correction makes a thick dark shared river, broad
colored tributaries, compact event and route cards, a strong merge capsule, and selection-opened deep
routes the dominant visual structure. The rejected screenshots under
`output/m15-phase06-story-river-proof-20260731` are comparison evidence only.

The replacement implementation is deliberately not called visually accepted yet. The focused proof
now confirms the fitting-room Route B owns its cross-label event, nested routes B.1/B.2 retain their
stream identity, rejoin and state-backlink navigation synchronize the panel, and neither required
desktop width has horizontal page overflow. User review is still pending.

The Phase 05 implementation beneath that presentation remains authoritative:

Build the story progressively from actual Ren'Py execution flow and state:

- collapse linear statements into readable corridors;
- split at menus and conditions;
- preserve nested choices;
- track assignments and link later gates back to the decisions that established them;
- follow jumps and calls to human-readable destinations;
- detect demonstrated rejoins and endings; and
- let AI summarize only after Python has built this structure.

The first proof is the Terrance route. The user accepted its family-tree reader on 2026-07-28.
The whole-game structure projection now accounts for all 149 parser labels: 134 are statically
reachable from `start`, 15 are unreachable, and all 6 reachable unresolved mechanics remain
explicit. Parser extraction and story coverage both grade PASS; resolution remains partial.
The first 10 cloud-AI corridor summaries also passed factual review. The corrected graph-backed
packetizer finds 604 Python-owned story-bearing chains and emits 597 narrative packets after seven
non-story-only chains are excluded. It accounts for all 12,191 reachable narrative statements
exactly once: 12,183 are included and 8 are explicitly excluded (the settings hint, adult setup
prompt/refusal, four save reminders, and the credits patron thank-you). All 1,823 reachable
control/effect facts remain available, including 205 direct state effects and 6 unresolved
mechanics. Packets include every incoming M06 rejoin origin and the next Python control point with
its arms; future AI beats remain presentation children of their original corridor.

The four user-visible Sol/High bulk tasks completed the remaining 587 summaries with zero deferrals.
Together with the accepted first 10, all 597 corridors grade PASS for factual fidelity. Packet shape
grades are 488 PASS, 80 PARTIAL, 26 LOW, and 3 FAIL. The three FAIL items are two old-save warnings
and one developer error, so they remain in coverage accounting but are excluded from the default
reader. A nine-corridor cross-game sample review passed. The 26 LOW items are mostly exact but
context-poor fragments and must be stitched into their owning branch or continuation rather than
rendered as standalone event cards.

The current correction keeps the existing 66-node, 75-edge structural walk authoritative while
replacing the stacked outline with a polished family-tree reader. Direct sibling routes fork
horizontally from their parent; deeper controls regain the full reading width beneath the exact
route that owns them. Python classifies the 22 projected arms as 12 continuations, 9 proven rejoins,
1 true ending, and 0 unresolved. The reader uses blue decisions, amber conditions, green continuing
paths, purple rejoins, and red only for the true unavailable ending. Concrete story detail still
opens inline, while variables, reachability, source lines, and evidence remain secondary.

The whole-game reader assembly now attaches all 594 reader-visible corridor summaries exactly once
under 111 Python-owned label events and their owning route flow. The full authority remains 324
controls and 700 menu/condition arms. The default story tree shows 260 controls and 571 arms; 64
startup, developer, and hint controls remain preserved in expandable technical detail instead of
interrupting the story. A real 1920x1080 browser inspection measured zero horizontal overflow for
both the page and the scrolling story surface. Three sibling arms measured 544, 528, and
375 pixels, concrete event and arm detail expanded in place, and decision, condition, continuation,
rejoin, ending, and unresolved colors remained distinct. The review copy and evidence are under
`output/m15-phase05-whole-game-reader-20260729` in the main Renpy checkout.

The coordinator correction removes the repeated structure-only fallback from all 202 affected arms.
Those arms now describe only their proven destination, next control, rejoin, ending, unresolved point,
or state change. The 29 labels without shared corridor prose render as neutral Python-control gates
with no borrowed child-route summary. The regenerated page and 1920px browser contain zero instances
of the rejected fallback or the former `Open the owning route below` helper, with structural and
outcome counts unchanged.

The 2026-07-30 UI rebuild removes the obsolete map, zoom, inspection, route-solver, narrative-job,
and organization surfaces from the default browser. The remaining reader has a story index,
client-side event search, wider forks, collapsible deep branches, concise outcome lines, and readable
expanded prose. It does not change Python story facts.

The 2026-07-31 Gate 1 implementation adds the smallest arm-owned cross-label route flow. The real
fitting-room proof places the called argument event only beneath `Keep arguing with her`; `Push her
out` bypasses it; the returned shared continuation remains canonical; loop or ambiguous reuse becomes
a stable reference rather than duplicated recursion. Recursive browser search, index navigation, and
count traversal include nested events. The focused 1920x1080 proof has no horizontal overflow, and an
in-memory invariant audit remains at 111 events, 594 corridors, 260 controls, and 571 arms. The full
reader has now been regenerated as a first-10 naming canary with the same totals and no overflow.

The deterministic story-name resolver uses accepted stable-ID wording, exact corridor titles, owning
event titles, or readable narrative before falling back explicitly. It never derives prose by
splitting identifiers. The initial real inventory contained 87 uncovered names; the coordinator's
10 accepted canary overrides reduced that to 74 because several named structural targets also resolve
dependent rows. The rendered canary shows the accepted condition question, event, destination, and
rejoin language while raw Python remains in secondary detail. Three user-visible Sol/High tasks
reviewed the remaining 74 items in 25/25/24 batches. Their 69 safe names plus the accepted first 10
resolve the entire final inventory: zero user-visible names remain uncovered. The accepted stable-ID
artifact is [`STORY_NAME_OVERRIDES.json`](milestones/M15_PHASE_05/STORY_NAME_OVERRIDES.json).

Completed progressive stories now hide dead Generate/readiness chrome, while actionable workflow
controls remain available. Recent project cards show source basename and precise last-opened time
without returning an absolute path; merely listing recent projects cannot migrate them.

Closed descendant routes now hide their content, selected-arm detail uses one route-wide slot capped
near 68 characters, and ordinary story buttons no longer use `aria-selected`. Later state gates now
carry path-compatible links to earlier assignments or explicit unresolved provenance. Destination
and rejoin rows navigate to stable story targets. The 1920x1080 final review has zero user-visible
underscored identifiers, raw expressions, rejected route headings, mechanical shared names, bare
`Otherwise`, or unnamed destination fallbacks; search, focus/highlight navigation, and Clear work
without console errors. Page and story overflow are both zero. Evidence and the disposable project
are under `output/m15-phase05-reader-corrections-20260731/final-review`.

## User-selected operating rules

- Full-width desktop scrolling timeline only.
- No pan, zoom, fit, 100%/200% variants, or mobile optimization.
- Trusted game execution is allowed; prefer a disposable headless run.
- Original inputs remain read-only.
- Game and script content may be sent to cloud AI.
- Cloud AI is the default; use a local LLM only when explicitly requested.
- Independent work is split into user-visible `gpt-5.6-sol` High Codex tasks in the sidebar unless
  the user says otherwise. Internal subagents do not satisfy a request for Codex tasks/threads.
- Bulk cloud summaries use a first-10 canary, then approximately equal parallel work across three or
  four user-visible Sol/High tasks.

## Rejected result

Generation `71a92c9d...e6987` and its 34-section outline are not accepted. Audit findings include
misassigned choices, missing arms, flattened nesting, false endings, opaque destinations, and clipped
summaries. Old counts such as 103/103 successful mapper calls prove transport completion only, not a
correct story timeline.

The 103 saved summaries, 105 transport chunks, earlier 24/34 groups, old local-only policies, and
historical Phase 04/Stage H/E rules are not active acceptance requirements.

## Authority

1. The user's latest explicit instructions.
2. `AGENTS.md` and `docs/MASTER_PLAN.md`.
3. The active Phase 05 contract.
4. This live project pointer.

Historical milestone documents are evidence only. They do not control current UI, provider,
privacy, model, testing, or orchestration decisions.
