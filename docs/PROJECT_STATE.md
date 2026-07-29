# Ren'Py Story Mapper project state

Updated: 2026-07-28

## Active work

- Active milestone: M15.1 Phase 05 progressive story walker.
- Contract: [`docs/milestones/M15_PHASE_05/GOAL.md`](milestones/M15_PHASE_05/GOAL.md).
- Task ledger: [`docs/milestones/M15_PHASE_05/TASKS.md`](milestones/M15_PHASE_05/TASKS.md).
- Branch: `main` after the accepted-proof integration.
- Status: Terrance family-tree proof accepted; full-game progressive walk is next.
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

The first proof is the Terrance route. The user accepted its family-tree reader on 2026-07-28;
full-game processing is now the next product step.

The current correction keeps the existing 66-node, 75-edge structural walk authoritative while
replacing the stacked outline with a polished family-tree reader. Direct sibling routes fork
horizontally from their parent; deeper controls regain the full reading width beneath the exact
route that owns them. Python classifies the 22 projected arms as 12 continuations, 9 proven rejoins,
1 true ending, and 0 unresolved. The reader uses blue decisions, amber conditions, green continuing
paths, purple rejoins, and red only for the true unavailable ending. Concrete story detail still
opens inline, while variables, reachability, source lines, and evidence remain secondary.

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
