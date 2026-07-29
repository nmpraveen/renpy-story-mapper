# Ren'Py Story Mapper project state

Updated: 2026-07-29

## Active work

- Active milestone: M15.1 Phase 05 progressive story walker.
- Contract: [`docs/milestones/M15_PHASE_05/GOAL.md`](milestones/M15_PHASE_05/GOAL.md).
- Task ledger: [`docs/milestones/M15_PHASE_05/TASKS.md`](milestones/M15_PHASE_05/TASKS.md).
- Branch: `codex/m15-phase05-whole-game-skeleton`.
- Status: whole-game reader assembled and browser-inspected; awaiting user acceptance.
- Native Codex goal: none.

## Current product decision

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
both the page and the 101,155px scrolling story surface. Three sibling arms measured 544, 528, and
375 pixels, concrete event and arm detail expanded in place, and decision, condition, continuation,
rejoin, ending, and unresolved colors remained distinct. The review copy and evidence are under
`output/m15-phase05-whole-game-reader-20260729` in the main Renpy checkout.

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
