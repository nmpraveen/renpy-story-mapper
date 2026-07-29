# Ren'Py Story Mapper repository rules

## Product outcome

- This is a quick script/game-to-story checker for desktop use.
- The primary result is a clean, full-width scrolling story timeline showing the linear story,
  choices, conditions, branch routes, important state changes, rejoins, and endings.
- Build the story progressively from Ren'Py execution flow. Do not use AI request chunks, source
  files, token limits, or arbitrary group counts as story-event boundaries.
- Prefer the smallest direct implementation that improves the real story output. Do not add
  production infrastructure, exhaustive safeguards, or process ceremony without a demonstrated
  product need.

## Story authority

- Python owns factual structure: labels, menus, nested choices, conditions, jumps, calls, returns,
  assignments, state provenance, branch destinations, rejoins, loops, terminals, and source lines.
- A branch is drawn where a menu or condition is evaluated. If an earlier choice or assignment
  enabled it, retain a dependency link back to that earlier point.
- Linear statements between control points may be collapsed into a readable story corridor.
- AI may name, summarize, explain, and editorially group Python-built corridors. AI must not invent
  or move choices, conditions, edges, effects, or rejoins.
- Dynamic behavior that cannot be established should be labeled unresolved, not guessed.

## Inputs and execution

- Original supplied game files remain read-only.
- Trusted games may be executed when useful. Prefer a disposable copy and headless execution so no
  visible game window appears. Files produced by Ren'Py stay outside the original game directory.
- Game scripts and story content in this project are not private and may be sent to cloud AI.
- Cloud AI is the default. Use a local LLM only when the user explicitly asks for local processing.
- Do not add consent manifests, privacy gates, provider fallback matrices, or cloud/local separation
  beyond the user's requested provider choice.

## Desktop interface

- Support the user's current desktop screen with a full-width scrolling timeline.
- Do not build pan, zoom, fit-to-screen, semantic zoom, 100%/200% variants, mobile layouts, or mobile
  optimization.
- Keep the main story readable while scrolling. Show branches locally, and use clear back-links or
  route badges for conditions caused many scenes earlier.
- Keep helper text minimal. Technical diagnostics and source evidence are secondary details.

## Codex collaboration and AI summaries

- In this repository, **Codex task** and **Codex thread** mean a separate user-visible task created
  with the Codex app's thread/task tools and shown in the sidebar. They do not mean an internal
  subagent.
- When the user asks to split work into Codex tasks or threads, create those user-visible tasks.
  Never substitute internal subagents for requested Codex tasks/threads or count subagents as them.
- When work contains multiple independent investigations or implementation areas, split them into
  separate user-visible Codex tasks using `gpt-5.6-sol` with High reasoning unless the user says
  otherwise.
- The coordinator owns scope, integration, and the final user-facing result. Parallel tasks receive
  bounded, non-overlapping work.
- For a bulk cloud-summary workload, the coordinator first processes and inspects the first 10
  items. Once those results are useful, divide the remaining items approximately evenly across
  three or four user-visible Sol/High Codex tasks and run them in parallel.
- Do not repeat a failed bulk pattern at scale. Correct the first-10 prompt or packet shape first.

## Validation and delivery

- Prove a new story-building approach on one real section before applying it to the whole game.
- During implementation, run only focused checks for the changed story/parser/UI seam.
- The key acceptance test is the rendered real story: correct branch membership, nesting,
  conditions, state back-links, destinations, and rejoins.
- Do not run broad CI, Release/package gates, repeated reviews, or PR preparation before the user
  accepts the story result or explicitly asks to ship it.
- Preserve unrelated user changes and never treat old milestone prose as current authority.
