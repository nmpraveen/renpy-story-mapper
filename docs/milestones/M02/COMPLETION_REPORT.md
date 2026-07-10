# M02 Completion Report - Semantic Scenes and Story Beats

Date: 2026-07-10

Platform authority: Windows

Runtime: CPython 3.12.10

Repository: `nmpraveen/renpy-story-mapper`

## Objective and scope

M02 converts the Phase 1 source-linked control-flow graph into deterministic scenes, narrative
beats, structural beats, and normalized transitions. The implementation remains entirely local,
does not use AI, does not evaluate expressions, and never executes Ren'Py, creator, screen, or game
Python code.

The milestone branch is `milestone/m02-semantic-scenes`. Pull request #3 is open at
<https://github.com/nmpraveen/renpy-story-mapper/pull/3> and is intentionally unmerged. It is
stacked on M01 documentation PR #2 until that documentation is merged or the M02 base is retargeted
to `main`.

## Delivered behavior

- Semantic schema version 1 with flat `scenes`, `beats`, `transitions`, and `unresolved` records.
- Stable scene, beat, transition, and unresolved IDs derived from Phase 1 evidence.
- Adjacent narration and dialogue grouped only across proven unambiguous fallthrough.
- Static dialogue speakers and literal text retained without evaluating or unescaping content.
- Multiline triple-quoted narration and dialogue retain speaker, text, and exact physical spans.
- Hard boundaries for labels, choices, conditions, jumps, calls, returns, merges, endings,
  unresolved behavior, and scope boundaries.
- Menu and conditional merges normalize forward to their actual continuation without invented
  loops or duplicate semantic routes.
- Choice captions and choice/branch conditions preserved on typed transitions.
- Calls preserve target transfers and distinct non-immediate `call_continuation` summary edges for
  static, dynamic, missing, and out-of-scope targets.
- Returns inside branches resolve to the proven post-branch continuation.
- Natural module fallthrough creates a scene-owned ending beat and concrete ending transition.
- Narrative, utility, and unknown label classification uses conservative deterministic evidence.
- Reachable and unreachable scenes and beats are retained.
- Dynamic, missing, out-of-scope, and unsupported behavior remains explicit and unresolved.
- Unsupported graph schema versions and unknown node or edge kinds fail closed with `ValueError`.
- The CLI now writes deterministic `semantic-story.json` beside the existing manifest and graph.
- Phase 1 graph input remains unchanged during semantic construction.

## Architecture

```text
Read-only RPA inventory
  -> preferred .rpy source
  -> inert Phase 1 parser
  -> source-linked control-flow graph
  -> deterministic semantic projection
       -> label-based scenes
       -> narrative and structural beats
       -> normalized typed transitions
       -> unresolved records
  -> semantic-story.json
```

The Phase 1 graph remains structural authority. M02 aggregates and normalizes its evidence but does
not create story routes from interpretation or AI.

## Worker tasks and integration

### Semantic model and grouping engine

- Task: `019f4d88-982d-7881-bf5d-6ad79d43bffc`
- Branch: `worker/m02-semantic-engine`
- Worker commits: `22f8488`, `0337303`, `0554492`, `bd9c358`
- Integrated commits: `f02b5d5`, `6b5fea9`, `699c969`, `8be37e3`
- Scope: `src/renpy_story_mapper/semantic.py`

### Fixtures and behavioral tests

- Task: `019f4d88-982d-7881-bf5d-6af22b8f6c4e`
- Branch: `worker/m02-semantic-tests`
- Worker commits: `e4cef60`, `1e90881`
- Integrated commits: `d2ffa71`, `b89059c`
- Scope: semantic fixtures and `tests/test_semantic.py`

### Independent correctness review

- Task: `019f4d92-65df-7202-83b9-c5957d24c66c`
- Branch/worktree: `review/m02-correctness`
- Initial review head: `0fe99e8`
- Initial result: three P1 and two P2 findings; fix then re-review
- Re-review head: `8be37e3`
- Final result: no remaining findings; accept

The initial review caught merge-route loops, dropped call-continuation summaries, absent natural
endings, multiline dialogue misclassification, and incomplete future-contract rejection even
though the original suite was green. The responsible implementation and test tasks were reopened,
the defects received regression coverage, and the same reviewer replayed the adversarial evidence
against the corrected head.

## Key integrated commits

| Commit | Purpose |
| --- | --- |
| `f02b5d5` | Initial deterministic semantic engine |
| `d2ffa71` | Initial semantic fixtures and behavioral contract |
| `3f93542` | CLI semantic JSON output and end-to-end test |
| `6b5fea9` | Align engine and independent public schema |
| `b89059c` | Review-driven routing regression fixtures/tests |
| `699c969` | Normalize merges, continuations, endings, multiline text, and contract validation |
| `8be37e3` | Final call-summary provenance and ending-transition correction |
| `62acdfd` | Explicit unknown-node regression |

## Windows acceptance verification

All commands ran from `C:\Users\prave\Documents\Codex\Renpy` in Windows PowerShell.

| Check | Command | Exit code | Result |
| --- | --- | ---: | --- |
| Runtime | `.\.venv\Scripts\python.exe --version` | 0 | Python 3.12.10 |
| Tests | `.\.venv\Scripts\python.exe -m pytest` | 0 | 50 collected, 50 passed in 0.19s |
| Ruff | `.\.venv\Scripts\python.exe -m ruff check .` | 0 | All checks passed |
| Strict mypy | `.\.venv\Scripts\python.exe -m mypy src` | 0 | No issues in 10 source files |
| Dependency health | `.\.venv\Scripts\python.exe -m pip check` | 0 | No broken requirements |
| Diff hygiene | `git diff --check` | 0 | No output |

Independent re-review additionally verified 100/100 shuffled node/edge permutations produced
byte-identical canonical JSON, graph input remained unchanged, archive-output collision protection
failed safely, and all prior finding reproductions closed.

## Canonical sample end-to-end evidence

The canonical read-only sample was analyzed twice into separate newly created Windows temporary
directories with identical arguments:

```powershell
.\.venv\Scripts\python.exe -m renpy_story_mapper analyze `
  "C:\Users\prave\University of Michigan Dropbox\Praveen Manivannan\Windows Mac portal\scripts.rpa" `
  --output-dir <unique-temporary-run-directory> `
  --entry-label start `
  --scope-glob '*script.rpy' `
  --scope-glob '*chapter1*.rpy'
```

Both runs exited 0. Each Phase 1 graph contained 654 nodes, 736 edges, and 5 unresolved nodes. The
semantic projection contained:

- 11 scenes
- 422 beats, including 64 narrative, 2 choice, and 28 condition beats
- 532 normalized transitions
- 24 unresolved records, including dynamic and out-of-scope semantic boundaries

| Output | Size | SHA-256 | Repeat result |
| --- | ---: | --- | --- |
| `import-manifest.json` | 54,688 bytes | `ea1c2fcc5cccc08c77cff25990137a38c19b24af3c6094c9cce8a7d71d524cb2` | Byte-identical |
| `story-graph.json` | 410,741 bytes | `390dd612765f457653c960b73fd9659562bf49fa3f3cbc8a77502edf5a7b2465` | Byte-identical |
| `semantic-story.json` | 1,157,179 bytes | `a27e887761fa05071a6f652448f38e3c9c9b7a3bc5efbdab4bd48e387c2e46fd` | Byte-identical |

Temporary outputs were removed after comparison.

## Canonical archive immutability

| Property | Before | After |
| --- | --- | --- |
| SHA-256 | `953fae213f32a9d0cae2432ef09924d2f9f83c960691f42a15b73cc747aade99` | `953fae213f32a9d0cae2432ef09924d2f9f83c960691f42a15b73cc747aade99` |
| Size | 70,031,252 bytes | 70,031,252 bytes |
| LastWriteTimeUtc | `2026-07-10T17:11:44.0000000Z` | `2026-07-10T17:11:44.0000000Z` |

Result: unchanged. No files were written beside the archive, and no content was extracted into the
sample directory.

## Known limitations and deferred work

- Scenes currently follow static label boundaries; richer scene inference is intentionally
  deferred until evidence supports deterministic rules.
- Dialogue and narration recognition is conservative. Literal escape sequences are preserved and
  not evaluated or unescaped.
- Utility-label classification requires narrow static evidence; ambiguous labels remain unknown.
- Dynamic expressions and creator-defined behavior remain unresolved rather than guessed.
- A natural-ending beat uses the Phase 1 synthetic `module_end` anchor span; its incoming ending
  transition carries the actual terminal statement span.
- M02 does not add SQLite persistence, incremental analysis, desktop UI, AI, packaging, or release
  artifacts.
- PR #3 remains open and unmerged. It is stacked on documentation PR #2.

## Infographic

`INFOGRAPHIC.png` was created with Codex's built-in native image-generation capability from the
facts in this report. It is a 1,672 x 941 RGB PNG (1,586,461 bytes) with SHA-256
`04dadcbe1d3bdcb6c9fcecb1ffd7d6c70342966eff6fbcd141f4d5858143f643`. The prompt requested a
Windows technical infographic covering the source-graph-to-semantic-JSON pipeline, M02
deliverables, verified metrics, canonical-sample counts, review closure, limitations, and M03 as
the next gated milestone. This Markdown report remains authoritative if generated text differs.

## Next milestone gate

M03 - Project persistence and incremental analysis is the next milestone in the master plan. No
M03 goal, task, branch, schema, or implementation has been created. It requires explicit user
approval after M02 review.

## Completion decision

M02 meets its functional, safety, determinism, provenance, Windows verification, review, and
archive-immutability acceptance criteria. The completion artifacts and native infographic exist,
PR #3 is ready for user review, and the milestone is complete.
