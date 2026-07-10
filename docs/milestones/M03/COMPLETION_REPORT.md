# M03 Completion Report - Story State and Durable Projects

Completed: 2026-07-10

Milestone branch: `milestone/m03-story-state-projects`

Accepted integrated head: `01944d023fe989d22e3640f77aa67f97f371ee84`

Milestone PR: `#5` - `https://github.com/nmpraveen/renpy-story-mapper/pull/5` (open and unmerged)

Runtime authority: Windows, CPython 3.12.10

## Outcome

M03 is complete. Ren'Py Story Mapper can now create, reopen, refresh, inspect, and delete versioned
SQLite projects for either a source folder or an RPA archive. Projects durably retain selected
source fingerprints, cached inert parser records, the M01 graph, the M02 semantic projection,
diagnostics, unresolved records, deterministic requirements, explicit state effects, and editable
state-variable metadata.

The implementation remains entirely static. It does not execute Ren'Py, creator-defined, screen,
or game Python code. Explicit literal syntax can become a proven fact; creator calls with visible
literal arguments are possible effects; computed, dynamic, opaque, and unsafe behavior stays
unresolved.

## Delivered behavior

### Versioned durable storage

- SQLite schema version 2 with an executable v1-to-v2 migration and pre-migration backup.
- Strict tables, primary keys, declared column types, nullability, dependency foreign keys,
  cascades, lookup-index shape, and source-size constraints are validated before a project opens.
- Corrupt, foreign, structurally incomplete, constraintless, wrongly typed, unexpectedly extended,
  or future-version projects fail through explicit safe errors.
- Canonical JSON payload hashes and deterministic public snapshots support byte-equivalent reopen
  verification.
- Create uses a temporary database and atomic publication. Refresh uses a staged validated backup
  when content changes. Cancellation rolls back transactions and preserves the last committed
  project. Delete stages the file before removal and restores it on failure.

### Incremental analysis

- SHA-256 source fingerprints select changed, unchanged, and removed sources.
- Parsed `ScriptModule` records are serialized to inert JSON and reconstructed without reparsing
  unchanged files.
- Source-to-source dependencies are derived from static calls and jumps; reverse closure reports
  the source data invalidated by a change.
- Derived rows record exact source dependencies so unrelated rows remain byte-identical.
- An unchanged refresh performs no parser call, no project backup, and no graph rebuild.
- If only a non-selected RPA entry changes, refresh transactionally updates the import manifest
  and archive fingerprint without reparsing selected `.rpy` files.
- Cancellation is checked before source reads, between folder files, around archive inventory, and
  inside transactional writes.

### Requirements, effects, and state variables

- Proven requirements cover safe names, boolean expressions, comparisons, and chained comparisons.
- Proven effects cover literal assignments and normalized numeric `+=`/`-=` deltas.
- Literal-argument creator calls are possible effects because their runtime behavior is not
  executed or assumed.
- Computed targets/values, dynamic calls, non-finite literals, unsupported operators, opaque
  Python blocks, and unsupported control flow are unresolved rather than silently dropped.
- Every fact retains its original expression, source path, and physical start/end lines.
- State categories cover relationships, skills, resources, jobs, locations, roles, flags,
  progression, and unknown creator-specific variables.
- User-edited display names and categories persist across unchanged, unrelated-source, and
  owning-source refreshes.

### Diagnostic interface

The Windows CLI now supports:

```text
renpy-story-mapper project create SOURCE PROJECT
renpy-story-mapper project refresh SOURCE PROJECT
renpy-story-mapper project show PROJECT [--output SNAPSHOT.json]
renpy-story-mapper project delete PROJECT
```

The CLI rejects a project path inside a selected game folder and never writes to the input archive.

## Worker tasks and integration

| Task | Responsibility | Delivered commit | Integration result |
| --- | --- | --- | --- |
| `019f4e18-a30e-71e1-984e-decff4c61faf` | SQLite project persistence | `28118f0` | Inspected and integrated as `5168e25` |
| `019f4e18-a276-7e73-84f5-8e9649eb85b8` | Deterministic state extraction | `0a0ab6d` | Inspected and integrated as `2429405` |
| `019f4e18-a314-73e2-b8e5-14bf93425b48` | Fixtures and black-box contracts | `095814f` | Inspected and integrated as `e34c549` |
| `019f4e29-6b9b-7171-b5c5-23bf062358e3` | Independent correctness review | Review-only | Accepted `01944d0`; no remaining P0-P3 findings |

The three initial worker tasks were stopped by a Codex usage-limit system error after producing
their assigned files. Their worktrees remained intact. The orchestrator inspected the actual
diffs, ran focused checks, anchored the worker commits, and integrated them; task status alone was
not treated as evidence.

## Review history

Independent review found and drove corrections for:

- structurally malformed SQLite schemas that initially opened too far;
- state-variable edits being overwritten on refresh;
- opaque Python/unsupported blocks disappearing instead of becoming unresolved;
- misleading signed-delta normalization;
- callable identifiers entering the state registry;
- non-finite numeric literals aborting project creation;
- quadratic per-label full-graph inclusion traversal;
- stale manifests when only non-source RPA entries changed;
- delayed cancellation before folder reads;
- wrong declared types and unexpected schema columns.

Every finding received a regression test. Final review of `01944d0` returned `ACCEPT` with no
remaining P0-P3 findings and independently passed 93 tests, Ruff, strict mypy, and `pip check`.

## Windows acceptance suite

Final orchestrator-owned run on `01944d0`:

| Command | Exit | Result | Elapsed |
| --- | ---: | --- | ---: |
| `.\.venv\Scripts\python.exe -m pytest -q` | 0 | 93 passed | 2.026 s |
| `.\.venv\Scripts\python.exe -m ruff check .` | 0 | All checks passed | 0.124 s |
| `.\.venv\Scripts\python.exe -m mypy` | 0 | No issues in 14 source files; project configuration is strict | 0.165 s |
| `.\.venv\Scripts\python.exe -m pip check` | 0 | No broken requirements | 0.313 s |
| `git diff --check` | 0 | No whitespace errors | less than 1 s |

The final suite contains persistence, migration, corruption, cancellation, deterministic reopen,
parser-cache, dependency-invalidation, state extraction, source evidence, synthetic RPA,
manifest-refresh, and M01/M02 regression coverage.

## Canonical archive acceptance

Read-only input:

`C:\Users\prave\University of Michigan Dropbox\Praveen Manivannan\Windows Mac portal\scripts.rpa`

All output remained under the ignored repository directory `artifacts\m03-acceptance`.

### Archive immutability

| Measurement | Before | After |
| --- | --- | --- |
| SHA-256 | `953fae213f32a9d0cae2432ef09924d2f9f83c960691f42a15b73cc747aade99` | identical |
| Size | 70,031,252 bytes | identical |
| LastWriteTimeUtc | `2026-07-10T17:11:44.0000000Z` | identical |

No file was created, modified, renamed, replaced, or unpacked beside the archive.

### Full project creation

Command:

```powershell
.\.venv\Scripts\python.exe -m renpy_story_mapper project create `
  "C:\Users\prave\University of Michigan Dropbox\Praveen Manivannan\Windows Mac portal\scripts.rpa" `
  ".\artifacts\m03-acceptance\canonical.rsmproj"
```

Result:

- Exit code: 0
- Elapsed: 334.183 seconds
- Project size: 715,141,120 bytes
- Project SHA-256: `a37125d2b2b91a26141f0d0c59391f232a0a46416034a92cbe18150014ee2727`
- Manifest: 154 entries, 77 selected `.rpy` sources, and 77 source/compiled pairs
- Graph: 405,449 nodes, 462,767 edges, and 171 graph-level unresolved nodes
- Semantic projection: 2,652 scenes, 252,061 beats, 309,329 transitions, and 171 semantic
  unresolved records
- State projection: 38,977 proven requirements and 55,356 proven/possible effects
- Combined public unresolved set: 8,545 records
- Observed peak working set during the run: at least 1,300,901,888 bytes (about 1.21 GiB)

An earlier full run exposed quadratic inclusion traversal and was deliberately stopped after
931.729 seconds with no payload commit. Its partial 57,344-byte project was verified inside the
workspace and removed. Commit `b2840b0` replaced one full traversal per label with one deterministic
multi-root traversal; independent review proved byte-identical graph output across shared calls,
unreachable roots, and cycles.

### Reopen and deterministic payload evidence

Closing and reopening produced the same 275-row authoritative payload manifest digest:

`9d62af29ba9d35f6ea0c02173bb7bef4d0704141277a3a777801bd07862af361`

SQLite `PRAGMA quick_check` returned `ok`. The project file remained byte-identical across the
final unchanged refresh.

### Required canonical facts

| Fact | Status | Exact evidence |
| --- | --- | --- |
| `ian_wits > 0` | proven requirement | `scripts/script.rpy:244` |
| `ian_charisma > 0` | proven requirement | `scripts/script.rpy:246` |
| `ian_lena_mmf_points += 1` | proven effect | `scripts/master_script.rpy:2256` |
| `ian_lena_dating = True` | proven effect | `scripts/gallery/gallery_scene_setups.rpy:1103` |
| `chapter = 3` | proven effect | `scripts/master_script.rpy:1994` |

### Unchanged refresh

Final accepted-head result:

- Exit code: 0
- Parsed sources: 0
- Reused sources: 77
- Invalidated sources: 0
- Removed sources: 0
- Elapsed: 0.655 seconds
- Project SHA-256 before/after: identical
- Archive SHA-256, size, and LastWriteTimeUtc before/after: identical

## Determinism and safety conclusions

- No embedded game or Ren'Py Python was executed.
- `.rpy` remained authoritative over matching `.rpyc`.
- Exact source and physical-line evidence survived SQLite round trips.
- AI was not used and no story text was sent to a cloud provider.
- Dynamic behavior was not guessed.
- No credentials, sample archive, extracted content, cache, environment, or acceptance project is
  tracked by Git.

## Limitations and deferred work

- Full canonical creation is CPU- and memory-intensive, and the resulting project is about 682 MiB.
  M04 must use progressive loading and virtualization; it must never load or render the entire
  graph at once.
- State categories are conservative name-based inferences and remain user-editable.
- Creator-defined calls are only possible effects even when their literal arguments are visible.
- Opaque Python and unsupported blocks produce block-level unresolved records because their bodies
  are never executed or interpreted.
- The CLI is a diagnostic harness, not the M04 desktop experience.
- No UI, AI grouping, installer, packaging, or M04/M05 feature was implemented.

## Next gate

M04 - Three-level Windows story map is proposed next. No M04 goal, task, branch, UI code, or
implementation has started. M04 requires explicit user approval after the M03 PR is reviewed and
merged.

## Completion infographic

`INFOGRAPHIC.png` was produced with Codex's native image-generation capability, copied into the
milestone folder, and visually checked against this report. It is a 1,672 x 941 RGB PNG,
1,798,283 bytes, with SHA-256
`6eb0cbfbeec2065ed5f48b53c4da932e9d91754620624a72750f003a228ce5f4`.

The Markdown report remains authoritative if generated-image typography is imperfect.
