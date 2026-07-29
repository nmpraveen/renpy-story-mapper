# Plan the simplest useful story result

## 1. Start with the rendered outcome

The user should be able to select a Ren'Py game or script and read its story as a full-width desktop
timeline. The timeline must make linear progression, choices, conditions, routes, important state
changes, rejoins, and endings understandable while scrolling.

## 2. Build progressively from execution flow

- Follow labels, fallthrough, jumps, calls, and returns from the entry point.
- Collapse linear statements between control points into story corridors.
- Split at menus and conditions.
- Track assignments and increments so later conditions link back to the choices or events that made
  them possible.
- Preserve nested choices and merge routes only at demonstrated rejoins.
- Use AI after this structure exists, never as the owner of mechanics.

## 3. Prove one real section first

Build and render one representative real-game section before processing the full game. Correct the
packet shape, branch tree, state tracking, and AI prompt there. Do not compensate for a failed proof
with more grouping, post-processing, or tests.

## 4. AI provider and parallelism

- Cloud AI is the default. Use a local LLM only when the user asks for it.
- Game and script content may be sent to cloud AI.
- "Codex task" and "Codex thread" mean app-created, user-visible tasks in the sidebar, not internal
  subagents. If the user asks for tasks/threads, never substitute subagents.
- When work has independent parts, use separate user-visible `gpt-5.6-sol` High Codex tasks unless
  the user says otherwise.
- For bulk cloud summaries, process and inspect the first 10 items first. If they are useful, split
  the remainder approximately evenly across three or four user-visible Sol/High tasks.

## 5. Desktop-only interface

Use the full width of the user's desktop screen and normal vertical scrolling. Do not plan pan, zoom,
fit, semantic zoom, 100%/200% variants, mobile layouts, or mobile optimization.

## 6. Testing and checkpoints

- Run focused tests for changed code while building.
- Inspect the rendered real section at the first useful checkpoint.
- After user acceptance, process the full game and run one focused integrated browser check.
- CI, Release, packaging, PR work, broad reviews, and repeated full suites are not prerequisites for
  showing or improving the story.

## 7. Keep rules current

Current user instructions outrank repository history. Keep current authority files concise. Historical
milestone reports may remain as evidence but must not impose active scope, provider, model, privacy,
testing, or UI requirements.
