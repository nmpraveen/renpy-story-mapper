# M05 Complex Branching Synthetic Fixture

This directory contains a wholly synthetic Ren'Py story used to exercise the deterministic
M01–M05 Story Mapper contracts at a readable, small scale. The story, characters, dialogue, route
names, and state variables are original test content. It contains no canonical game text, copied
sample material, external assets, imports, Python blocks, screen code, filesystem or network
access, or executable helper code. It is intended only for static analysis and must never require
Ren'Py execution.

## Route topology

`start` initializes explicit state and jumps to `harbor_arrival`. The arrival menu can send the
reader directly toward the lighthouse or archive, or through `market_rounds` for preparation. The
arrival and market sections contain three nested menus and a mixture of unconditional and gated
choices.

`market_rounds` is a controlled graph loop. Entering it increments `market_rounds`; the rescue
branch jumps back only while `market_rounds < 2`, while all other outcomes leave for a main route.
This represents a visible strongly connected component without using unsupported `while` syntax.

`lighthouse_route` and `archive_route` contain route-specific dialogue, gates, and effects. The
lighthouse can redirect into the archive. Both routes call `shared_council`, return to distinct
continuation lines, and then jump into the cross-route merge at `final_confrontation`. The finale
branches to good, bad, neutral, and secret ending labels.

The secret choice is deliberately reachable only after earlier state changes: it requires
`secret_chart and trust >= 2 and courage > 0`. The chart can be discovered through gated route
content, while trust and courage must be accumulated by prior decisions.

## Why the constructs exist

- Explicit comparisons cover `trust >= 2`, `courage > 0`, `coins >= 3`, inventory flags,
  progression counters, and route/flag combinations.
- Literal assignments, `+=`, and `-=` cover relationship, skill, money/resource, inventory,
  route/flag, support, and progression state.
- Nested menus and 27 displayed choices exercise choice captions, conditional availability,
  branch-local effects, fallthrough, and menu merges.
- Two calls to `shared_council` exercise shared content, call-continuation edges, one return with
  multiple statically known continuations, and post-return route flow.
- Explicit jumps form splits, the controlled market loop, route redirection, cross-route merges,
  and four terminal outcomes.
- `jump expression emergency_route` is intentionally dynamic. Static analysis must retain exactly
  one unresolved `dynamic_jump_target` record and must not evaluate or guess the destination.
- Dialogue and narration around every structural construct give deterministic grouping and
  presentation layers enough human-readable evidence to form meaningful beats and groups.

## Ground truth and acceptance checks

[`expected.json`](./expected.json) is the machine-readable authority for this fixture. It records
the source SHA-256 and physical line count; labels; every displayed choice; every gate and safe
effect with its physical source line; call, jump, return, merge, and loop relationships; ending
types; the unresolved transfer; and minimum deterministic graph, semantic, state, and presentation
counts.

Acceptance should analyze this directory with Windows CPython 3.12 and entry label `start`, writing
the `.rsmproj` and any exported output only to a Windows temporary directory. A conforming run has:

- 351 physical source lines, 11 reachable labels, and 27 displayed choices;
- 369 graph nodes, 408 graph edges, and all 369 nodes reachable from `start`;
- 11 semantic scenes, 212 beats, 256 transitions, and one unresolved record;
- 26 proven requirements, 88 proven effects, and 14 registered state variables;
- 282 presentation nodes, 404 presentation edges, 212 evidence rows, 114 fact rows, and 39
  structural groups;
- two calls into `shared_council`, returns to both route continuations, the `market_rounds`
  back-edge, the merge at `final_confrontation`, and all four ending labels; and
- exactly one unresolved dynamic target at `complex_story.rpy:298`.

The exact counts above are the observed deterministic baseline as well as conservative minimums.
Any intentional parser or presentation contract change should be reviewed against the detailed
source evidence before updating the manifest. No acceptance step may invoke a cloud provider, LM
Studio, embedded Python, or the Ren'Py runtime.
