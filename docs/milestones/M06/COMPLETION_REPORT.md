# M06 Completion Report — Safe Source Recovery and Correct Route Semantics

Date: 2026-07-12

Status: Complete; PR #9 is published and must remain unmerged until explicit user approval.

Milestone branch: `codex/m06-safe-ingestion-route-semantics`

Baseline: `7b5deeeeeab35a358eb78b7b660d3d57c02717b2`

## Outcome

M06 adds a safe, unified Windows ingestion path for common modern Ren'Py inputs and a deterministic
control-region layer that distinguishes reconvergent detours from persistent routes. No game or
Ren'Py Python was executed, no source was modified, and cloud story analysis was not used.

The application can now accept a game folder, a parent folder containing `game`, direct `.rpy`,
direct `.rpyc`, direct `.rpa`, or an existing `.rsmproj`. The Windows UI retains separate Folder and
File actions but both use the unified ingestion boundary; File accepts `.rpy`, `.rpyc`, and `.rpa`.

## Delivered behavior

### Source discovery and recovery

- Deterministic precedence is loose original `.rpy`, archived original `.rpy`, loose reconstructed
  `.rpyc`, then archived reconstructed `.rpyc`.
- Identical same-tier inputs deduplicate; conflicting same-tier inputs fail as ambiguous.
- The existing bounded RPA reader remains authoritative. UnRPA is neither included nor invoked.
- A stripped Unrpyc runtime runs in a dedicated Windows helper created suspended, attached to a
  one-process kill-on-close Job Object, then resumed.
- The child receives a minimal non-secret environment, isolated Python flags, bounded input,
  decompression, output, memory, log, process, and wall-time limits, plus filesystem/network/
  subprocess/dynamic-library audit restrictions.
- Recovery cache is content-addressed and must live outside the selected game/source.
- Partial recovery is opt-in. Incomplete coverage persists a warning and blocks AI before provider
  creation until the user explicitly acknowledges it.
- Reconstructed evidence is labeled separately from original physical source and records input,
  output, tool, commit, bundle, options, line basis, warnings, and cache status.
- Explicit recovered-source export requires a new destination outside the source/game and writes a
  provenance manifest plus its SHA-256.

### Pinned third-party runtime

- Upstream: CensoredUsername/Unrpyc
- Tag: `v2.0.4`
- Upstream internal version: `2.0.3`
- Commit: `3ae8334ed71a05535927dcc559663d3aca51215b`
- Runtime bundle SHA-256: `fb764521f9d3120b0c62198f086226f837802d73eccc9cad3c2ad683b1117775`
- License: MIT, retained in the source tree and wheel
- Included runtime modules: six
- Excluded: injector, upstream CLI, deobfuscation, translation, testcases, AST dumper,
  multiprocessing entry point, `un.rpyc`, and UnRPA

### Schema v5 and project lifecycle

- Added source derivations, recovery results/failures, durable coverage state, AI-block state, and
  explicit acknowledgement.
- Added persisted `m06_control_flow` authoritative payloads and snapshot exposure.
- Migrations from older versions are one atomic transaction; injected v5 failure leaves v3 intact.
- Create, refresh, reopen, cache replay, corruption validation, and dependency-scoped invalidation
  remain transactional.

### Deterministic route semantics

- Normalized call graph uses call-site return summaries without legacy return cross-products.
- Procedure summaries distinguish returning, concretely terminating, divergent, recursive,
  looping, and unresolved behavior.
- Iterative SCC analysis distinguishes loop body, dominance-proven back-edge, loop exit, self-loop,
  and irreducible multi-entry SCC diagnostics.
- Immediate post-dominators prove concrete merges; the virtual exit is never displayed as a merge.
- Regions classify local detour, optional detour, reconvergent route segment, persistent route,
  terminal split, loop choice, or unresolved behavior.
- Only proven scalar assignments and proven requirements participate in conservative state-selector
  lineage. Point deltas never manufacture persistent routes.
- Arm membership and terminal summaries are bounded through SCC-condensed analysis; each node has
  one deterministic innermost ownership record.
- Quotient connections preserve all semantic roles, control-edge IDs, and ordered evidence instead
  of selecting one dominant edge kind.

## Worker tasks and integration

| Task | Delivered commits | Integration/result |
|---|---|---|
| Source ingestion/recovery `019f56ee-f096-70a2-8153-4b78baa8e3f7` | `0e7cd8a` | Integrated as `6ecc2dd`; broad accidental formatter changes were rejected and removed before delivery |
| Control regions `019f56ee-f096-70a2-8153-4b5bc768eb46` | `64adaab`, `9f025e1`, `0384ca3`, `1b3441c` | Integrated as `0c18293`, `1611725`, `848b3c6`, `eb850dc`; three correctness/performance corrections returned to owner |
| Independent review `019f5712-5e51-7a81-9e78-4ac5815df620` | `8cc1e1a`, `eb8dfe9`, `0f55d8d` | Initial NO-SHIP findings reproduced; final re-review recommends SHIP with no remaining P0-P3 finding |

Two delayed duplicate control tasks were stopped and archived before their output was accepted;
their IDs and cancelled status remain recorded in `TASKS.md`.

Orchestrator integration commits include `f64c8ef` (persist control analysis), `5b3837b` (unified
Windows UI input), `553c180` (security-review blockers), and `ee87c31` (all review tests required).

## Windows verification

Runtime authority: CPython 3.12 on Windows.

Baseline before implementation:

```text
python -m pytest -q                         exit 0 — 348 passed
python -m ruff check src tests scripts      exit 0
python -m mypy src/renpy_story_mapper       exit 0 — 34 source files
python -m pip check                         exit 0
```

Final integrated acceptance after the reviewed implementation (`fcc2345`):

```text
python -m pytest -q                         exit 0 — 376 passed in 20.30s
python -m ruff check src tests scripts      exit 0
python -m mypy src/renpy_story_mapper       exit 0 — 42 source files
python -m pip check                         exit 0
git diff --check                            exit 0
```

Closeout rerun after adding the report and native infographic: 376 tests passed in 20.52 seconds;
Ruff, strict mypy across 42 source files, and `pip check` all exited 0.

Independent final re-review:

```text
focused control/review tests                exit 0 — 10 passed
full pytest                                 exit 0 — 376 passed in 20.25s
Ruff / strict mypy / pip check / diff       exit 0
recommendation                              SHIP; no P0-P3 findings
```

Performance evidence:

| Harness | Result |
|---|---|
| 10,000 nodes / 14,998 edges | 1.419s; about 26.5 MB additional traced peak |
| 2,000-node persistent-split chain | 0.496s; about 5.1 MB; 1,998 bounded arm memberships |

Wheel verification:

- `pip wheel . --no-deps`: exit 0
- Wheel members: 59
- Runtime modules: 6
- Required notice, license, and pin: present
- Forbidden UnRPA/injector/deobfuscation/testcase/translation paths: absent
- Wheel SHA-256: `1aa301be63a36c497c765d60c0f31d22fb1294b17f2f14fc0e88f5ac344a120a`

## Small-script end-to-end validation

Outputs were written only under:

`C:\Users\prave\AppData\Local\Temp\rsm-m06-small-20260712-122834`

### Original `.rpy`

- Input: `script small new.rpy`
- SHA-256: `d3a4e0a305c6c8a8d84ff5bd99845a4035f0bde7ce953699af71d607806d7f71`
- Size: 9,994 bytes
- LastWriteTimeUtc: `2026-03-27T22:21:22Z`
- Result: schema v5; 49 graph nodes; 51 edges; 3 control regions; 7 arms; 4 terminals
- Route result: one proven local detour and two unresolved regions retained conservatively
- Authority SHA-256: `02238188771ccc8de0b8b6913c9b075b3471659d3c8108c84b6c781b61419662`

### Compiled-only `.rpyc`

- Input: `script smaller version.rpyc`
- SHA-256: `0ae658c6617c119abe5e65c00e34bf6c79c213e5b6a466a00ff2e9bbdb1a3ddc`
- Size: 30,533 bytes
- LastWriteTimeUtc: `2026-05-23T06:19:06Z`
- Recovery: complete; output 22,839 bytes; output SHA-256
  `9eaa6b357b1571aea65524360f5054f6c6f7c2336085a067480f406a6d06692d`
- Result: schema v5; 339 graph nodes; 345 edges; 2 control regions; 4 arms; 3 terminals
- Route result: two true terminal splits
- Authority SHA-256: `9dc1a23c5661937b5ecdaf6271cf0c3898acf0ec15744b2e45da3258d4695948`
- Unchanged refresh: parsed 0, reused 1, invalidated 0, removed 0; cache hit true; authority hash unchanged
- A second forced uncached run passed using the sanitized suspended helper boundary.
- Explicit recovered-source export produced the qualified reconstructed `.rpy` plus provenance files.

Both inputs retained byte-identical SHA-256, size, and `LastWriteTimeUtc` after all operations.
The canonical `scripts.rpa` was not accessed during M06.

## Limitations and deferred work

- Recovery intentionally supports modern `RENPY RPC2` inputs. Ancient Python 2-era, obfuscated,
  modified, or unsupported compiled formats fail explicitly.
- Full AppContainer/restricted-token filesystem and network capability enforcement is not yet
  packaged. This is non-blocking for the current source-form milestone because packaging and public
  distribution are excluded. The tested Job Object, minimal environment, audit, bounds, cache, and
  no-game-write controls remain mandatory.
- Folder discovery does not inspect executables, APKs, ZIP/7z archives, or disk images.
- M06 does not implement the M07 two-level flowchart or parallel Luna orchestration.
- No full MsDenvers cloud analysis was rerun.

## Required artifacts

- Goal: `docs/milestones/M06/GOAL.md`
- Task ledger: `docs/milestones/M06/TASKS.md`
- Independent review: `docs/milestones/M06/INDEPENDENT_REVIEW.md`
- Completion report: this file
- Native infographic: `docs/milestones/M06/INFOGRAPHIC.png` (generated during final closeout)
- Pull request: https://github.com/nmpraveen/renpy-story-mapper/pull/9 (unmerged)
