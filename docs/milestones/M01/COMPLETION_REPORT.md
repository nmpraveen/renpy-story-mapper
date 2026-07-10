# M01 Completion Report - Phase 1 Analyzer Foundation

Date: 2026-07-10
Platform authority: Windows
Runtime: CPython 3.12
Repository: `nmpraveen/renpy-story-mapper`

## Objective and scope

M01 establishes a safe, deterministic, source-linked Phase 1 analyzer for Ren'Py archives. This
closeout documents the accepted implementation in PR #1, performs the required Windows regression
verification, confirms deterministic output and archive immutability, and creates the milestone
artifacts. It does not repeat a standalone audit, merge PR #1, or begin M02.

## Integration state

- Branch: `agent/phase-1-analyzer`
- Baseline and current implementation commit:
  `0ef367e5085cabb3c9e1a0ea31e4bb2b31334dcc`
- Commit subject: `Add Phase 1 Ren'Py story analyzer`
- Pull request: `#1` - `Add Phase 1 Ren'Py story analyzer`
- PR head and base: `agent/phase-1-analyzer` into `main`
- PR state at verification: open, non-draft, and mergeable
- PR URL: <https://github.com/nmpraveen/renpy-story-mapper/pull/1>
- Merge action during verification: not performed; explicit user approval was required

The Phase 1 commit contains 21 files with 2,296 insertions and 2 deletions.

### Post-completion integration update

After M01 completion and explicit user approval, PR #1 was merged on 2026-07-10 as commit
`80d6734b5d5df81d9e2584d31845b1fdcdca39a3`. The M01 completion artifacts were then committed on
`docs/m01-closeout` and submitted as documentation PR #2.

## Delivered behavior

- Read-only RPA 3.0 archive inventory with validation limits.
- Restrictive index unpickling that rejects globals and persistent IDs.
- Streaming source reads without extracting beside the game.
- `.rpy` precedence over a matching `.rpyc` source.
- Inert static parsing for labels, menus, conditions, jumps, calls, returns, and fallthrough.
- Explicit unresolved nodes for unsupported or dynamic behavior.
- Source-linked nodes with physical line spans and retained text evidence.
- Directed typed control-flow edges, stable node IDs, reachability, and diagnostics.
- Deterministic `inspect` and `analyze` CLI JSON output.
- Automated parser, graph, and archive-safety tests.

## Architecture and flow

```text
Read-only game archive
  -> bounded RPA inventory and safe source streaming
  -> .rpy-over-.rpyc selection
  -> inert Ren'Py subset parser
  -> source-linked control-flow graph
  -> deterministic manifest and graph JSON
```

No embedded Ren'Py, game, screen, creator, or Python code is executed. Expressions and dynamic
targets are retained as evidence but are not evaluated or guessed.

## Established sample evidence

The pre-existing Phase 1 artifact at `artifacts/prologue-chapter-1` records:

- 154 archive entries: 77 `.rpy` and 77 `.rpyc`.
- 77 selected source files and 77 source/compiled pairs.
- Read-only streaming, `.rpy` source precedence, no decompilation, and no creator-code execution.
- A graph containing 8,000 nodes and 8,437 edges across 39 scoped labels.
- 7,928 nodes reachable from the entry and 34 reachable labels.
- 8 unresolved constructs and 0 diagnostics.
- Matching before/after archive identity with `verified_unchanged: true`.

These are established Phase 1 results, not a newly repeated standalone audit.

## Windows acceptance verification

All commands ran from `C:\Users\prave\Documents\Codex\Renpy` in Windows PowerShell.

| Check | Command | Exit code | Result |
| --- | --- | ---: | --- |
| Runtime | `.\.venv\Scripts\python.exe --version` | 0 | Python 3.12.10 |
| Tests | `.\.venv\Scripts\python.exe -m pytest` | 0 | 33 collected, 33 passed in 0.15s |
| Ruff | `.\.venv\Scripts\python.exe -m ruff check .` | 0 | All checks passed |
| Strict mypy | `.\.venv\Scripts\python.exe -m mypy src` | 0 | No issues in 9 source files |
| Dependency health | `.\.venv\Scripts\python.exe -m pip check` | 0 | No broken requirements |

### Deterministic end-to-end check

The canonical archive was analyzed twice into two newly created Windows temporary directories with
the same command arguments:

```powershell
.\.venv\Scripts\python.exe -m renpy_story_mapper analyze `
  "C:\Users\prave\University of Michigan Dropbox\Praveen Manivannan\Windows Mac portal\scripts.rpa" `
  --output-dir <unique-temporary-run-directory> `
  --entry-label start `
  --scope-glob '*script.rpy' `
  --scope-glob '*chapter1*.rpy'
```

Each run exited 0 and reported 654 nodes, 736 edges, and 5 unresolved constructs. The temporary
outputs were removed after comparison.

| Output | Size | Run 1 SHA-256 | Run 2 SHA-256 | Result |
| --- | ---: | --- | --- | --- |
| `import-manifest.json` | 54,688 bytes | `ea1c2fcc5cccc08c77cff25990137a38c19b24af3c6094c9cce8a7d71d524cb2` | `ea1c2fcc5cccc08c77cff25990137a38c19b24af3c6094c9cce8a7d71d524cb2` | Byte-identical |
| `story-graph.json` | 410,741 bytes | `390dd612765f457653c960b73fd9659562bf49fa3f3cbc8a77502edf5a7b2465` | `390dd612765f457653c960b73fd9659562bf49fa3f3cbc8a77502edf5a7b2465` | Byte-identical |

## Canonical archive immutability

The archive was opened only for read-only regression analysis. Identity was captured immediately
before and after both runs:

| Property | Before | After |
| --- | --- | --- |
| SHA-256 | `953fae213f32a9d0cae2432ef09924d2f9f83c960691f42a15b73cc747aade99` | `953fae213f32a9d0cae2432ef09924d2f9f83c960691f42a15b73cc747aade99` |
| Size | 70,031,252 bytes | 70,031,252 bytes |
| LastWriteTimeUtc | `2026-07-10T17:11:44.0000000Z` | `2026-07-10T17:11:44.0000000Z` |

Result: unchanged. Nothing was written beside, extracted into, renamed, replaced, or modified in
the canonical sample location.

## Worker contributions

No separate worker task was needed. Phase 1 implementation was already established, and this
bootstrap consisted only of orchestrator-owned integration verification, documentation, and native
infographic generation. See `TASKS.md`.

## Known limitations and deferred work

- The parser intentionally supports a conservative static subset, not all Ren'Py syntax.
- `.rpyc` decompilation is not attempted.
- Expression truth, dynamic jump/call targets, creator statements, Python control flow, screens,
  and ATL are not interpreted; unknown behavior remains unresolved.
- The underlying output is a low-level control-flow graph, not yet semantic scenes or story beats.
- There is no project database, desktop UI, AI enrichment, advanced route explorer, packaging, or
  release artifact in M01.
- Phase 1 is merged, but no packaged release exists yet.

## Infographic

`INFOGRAPHIC.png` was created with Codex's native image-generation capability using the verified
facts in this report. It is a 1,672 x 941 RGB PNG (1,660,292 bytes) with SHA-256
`65939401dc0609fd5e0b5af7269421844cb6961683100a956ffe96ffbf60dcd6`. The prompt requested a
Windows technical infographic covering the five-stage static-analysis flow, Phase 1 deliverables,
verified metrics, established sample counts, design limitations, and M02 as the next gated step.
The image is a visual summary; this report remains authoritative if generated text differs.

## Next proposed milestone

M02 - Semantic scenes and story beats is the next proposed milestone. It may begin only after
explicit user approval and creation of its own single self-goal. The master plan suggests three
bounded local tasks:

1. Semantic model and grouping engine: schema, deterministic grouping, and structural boundaries.
2. Fixtures and behavioral tests: focused fixtures for dialogue, menus, conditions, calls, returns,
   endings, provenance, and source ranges.
3. Independent correctness review: grouping semantics, determinism, provenance, and regressions;
   review-only unless reassigned.

The orchestrator would own CLI integration, conflict resolution, final Windows verification,
documentation, infographic generation, and the approval gate.

M02 acceptance criteria are:

- Identical input produces byte-identical semantic output.
- Every beat maps to exact source lines.
- Choices and conditions retain their graph edges.
- No AI or game-code execution is required.
- Existing Phase 1 behavior remains compatible.
- Pytest, Ruff, strict mypy, and `pip check` pass on Windows.

## Completion decision

M01 meets its documented acceptance criteria. Its factual record is this Markdown report; the
infographic is a visual summary and may contain generated-text imperfections. M02 was unstarted at
the completion decision and remained gated on explicit approval.
