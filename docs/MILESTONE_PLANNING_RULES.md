# **PLAN THE SIMPLEST USEFUL SCRIPT-TO-STORY RESULT**

These rules apply to Phase 04 and every future Ren'Py Story Mapper milestone.

## 1. Start with the user outcome

Write one plain-language sentence describing what the user will be able to do. For this project the
default outcome is:

> Load Ren'Py game files and quickly read a rough whole-story overview with the important choices,
> routes, state changes, and rejoins.

Anything that does not directly support that sentence begins outside the phase.

## 2. Define three scope lists

Every phase plan must state:

- **Must work now:** the smallest real end-to-end behavior the user needs.
- **Useful later:** improvements that are deliberately deferred.
- **Do not build:** production hardening, theoretical edge cases, and unrelated architecture.

Do not promote an item from the second or third list because it seems elegant, standard, safer in
the abstract, or already exists in an older plan. Require a demonstrated current-product blocker or
new explicit user approval.

## 3. Test the real example early

Choose the smallest real acceptance example before designing internals. Run it as soon as the
shortest vertical path exists. For story mapping, inspect whether the output gives:

- a readable chronological story overview;
- visible choices and branch outcomes;
- persistent routes and proven rejoins where available;
- important state changes that explain how a route is reached; and
- a usable link back to detail/source evidence.

The output is for quick personal checking. Approximate summaries are acceptable. Perfect wording,
publication accuracy, reproducible AI prose, exhaustive line ownership, and formal proof are not
default requirements.

## 4. Use three to five gates

A normal phase should have no more than five gates:

1. Freeze the smallest scope and pass one lightweight semantic review.
2. Build the shortest end-to-end path with at most two independent workers.
3. Run the real example and let the user inspect it.
4. Fix only blockers found in that inspection.
5. Run one final integrated review, sharded CI, and one Release/package gate.

Stop after each user-visible gate. Do not automatically begin the next gate if the outcome raises a
scope question.

## 5. One Orchestra, few workers

- One user-visible Orchestra task owns the goal, scope decisions, worker briefs, integration, and
  checkpoint reports.
- The Orchestra guards against diversion and overengineering; it does not implement every track
  itself.
- Use at most two concurrent workers unless the user explicitly approves more.
- Every worker receives an exact base, owned files, one bounded output, exclusions, and focused
  checks.
- Use one early semantic reviewer and one final integrated reviewer by default. Do not create a
  reviewer for every worker unless a concrete risk requires it.
- Monitor only completion, blocking findings, or user-decision checkpoints. Do not burn quota on
  minute-by-minute polling or commentary.

## 6. The user chooses models each time

At the start of every phase or resumption, record the user-selected settings separately for:

- the planning/Orchestra task;
- implementation workers; and
- reviewers, if different.

Do not inherit settings from an earlier phase and do not silently escalate reasoning. Repository
text cannot set the running model, so each task creation must pass the settings explicitly and
report when a selector is unavailable.

For the next Phase 04 resumption, workers and reviewers use `gpt-5.6-sol`, Medium reasoning, and
fast mode disabled. The user intends to create the new planning/Orchestra chat with Ultra
reasoning; the chat must verify its actual setting rather than claiming the repository changed it.

## 7. Use a quota-aware test ladder

- **While editing:** run the directly affected tests and lint/type checks for changed files.
- **At one integration checkpoint:** run the focused Story Map V2 workflow/browser set.
- **At PR candidate:** push once and use the repository-wide timing-balanced sharded CI.
- **At final intended head:** run the Windows Release/package gate once.

Do not run the entire suite after every worker, correction, commit, or push. Do not keep an agent
active merely to watch healthy CI. If a cheap check fails, fix it before starting the expensive
gate.

## 8. Pause and ask when scope starts growing

The Orchestra must pause the goal and ask the user before:

- adding a new database schema, protocol version, scheduler, migration, or recovery subsystem;
- creating a new product workflow when an existing path could be made good enough;
- adding extreme-scale or exhaustive crash/tamper matrices not triggered by the real game;
- creating more than two concurrent workers or more than the two default reviews;
- starting a second correction loop for the same design problem;
- changing the user-selected model/reasoning settings;
- making a private provider call not already covered by an exact preview and consent; or
- expanding the phase beyond the one-sentence user outcome.

## 9. Completion means useful, not perfect

A milestone is ready when the real user workflow works, the output is useful for rough personal
story checking, privacy/read-only boundaries hold, blocking findings are resolved, and the lean
final gates pass. It is not blocked by missing production-grade guarantees that the user did not
request.
