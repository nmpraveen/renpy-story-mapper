# M06 Independent Security, Compatibility, and Correctness Review

Review date: 2026-07-12

Reviewer branch: `codex/m06-security-review`

Integrated base reviewed: `f64c8ef241f0773d43f03cab71c52f101ae8dc6b`

Production diff reviewed: `3125743..f64c8ef`

## Recommendation

**NO-SHIP.** The integrated implementation has six independently reproduced P1 defects and one
P2 supply-chain metadata defect. The positive baseline suite remains green because the review
regressions are retained as strict expected failures; running them with `--runxfail` reproduces
all six implementation failures.

No production code was changed by this review.

## Scope and method

The review read `docs/MASTER_PLAN.md`, `docs/milestones/M06/GOAL.md`, and
`docs/milestones/M06/TASKS.md` completely, then inspected every production and vendored-runtime
change in `3125743..f64c8ef`. The review covered input discovery, source precedence, path and
archive safety, compiled recovery isolation, cache/provenance/export behavior, schema migrations,
AI coverage enforcement, control-flow semantics, persistence, deterministic output, performance,
and wheel contents.

The canonical archive and all MsDenvers archives/walkthrough material were not accessed. No cloud
AI command or provider was run.

## Findings

### P1-1 — Incomplete recovery does not block cloud organization

Owner: M05/M06 organization boundary, `src/renpy_story_mapper/ui/organization_workflow.py:164`.

`source_coverage.ai_transmission_blocked` is persisted and can be acknowledged, but no organization
entry point reads it. `OrganizationWorkflow.organize()` obtains the provider immediately after
ordinary per-run cloud consent. A partially recovered project can therefore send its incomplete
story payload to the cloud without the M06-specific acknowledgement required by the master plan.

Reproduction:

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path
& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m pytest `
  tests/test_m06_security_review.py::test_incomplete_source_coverage_blocks_provider_construction `
  --runxfail -q
```

Observed: the provider factory is reached and raises
`AssertionError: provider boundary reached for blocked source coverage`.

### P1-2 — The desktop application still bypasses unified M06 ingestion

Owner: desktop lifecycle, `src/renpy_story_mapper/ui/project_controller.py:20`, `:68`, and `:245`.

The production desktop backend still calls `create_archive_project`/`create_project` and
`refresh_archive_project`/`refresh_project`. Its path validator rejects every direct file except
`.rpa`. Consequently the primary app cannot create projects from direct `.rpy` or `.rpyc`, and a
folder follows the old loose-`.rpy` path instead of the new four-tier recovery path. The new CLI
boundary does not satisfy the common desktop-product input contract.

Reproduction: run the direct-compiled-source review test with `--runxfail`. It fails at
`project_controller.py:252` with `ValueError: Select a game folder or an RPA archive.`

### P1-3 — Folder archive discovery follows symlinks outside the selected game root

Owner: ingestion discovery, `src/renpy_story_mapper/ingestion/service.py:71` and `:258`.

Loose `.rpy`/`.rpyc` candidates are resolved and checked against the selected root, but discovered
`.rpa` files are not. On this Windows host a file symlink `game/linked.rpa` targeting an archive
outside the selected tree was accepted and its story source was inventoried. This crosses the
user-selected read boundary and violates the symlink/reparse escape contract.

Reproduction: run
`test_folder_discovery_rejects_symlinked_archive_escape` with `--runxfail`. Expected
`IngestionError`; observed no exception.

### P1-4 — Recovery helper policy does not contain filesystem writes or sterilize environment

Owner: recovery isolation, `src/renpy_story_mapper/ingestion/helper.py:54` and
`src/renpy_story_mapper/ingestion/runtime.py:186`.

The audit hook denies network/process/`ctypes.dlopen` events but permits every `open` event,
including writes outside the private work directory. `CreateProcess` also receives `None` for its
environment block and therefore inherits the parent environment. The Job Object correctly bounds
memory/process count and kills on close, but it does not provide filesystem or secret isolation.
This leaves a vendored unpickler/decompiler compromise with ambient read/write authority, contrary
to the explicit arbitrary-output, environment, and no-game-write boundary.

Reproduction: run `test_recovery_helper_audit_denies_arbitrary_file_write` with `--runxfail`.
Calling the installed audit policy for an outside `open(..., "w")` does not raise.

### P1-5 — v3-to-v5 migration is not atomic across the full migration

Owner: schema lifecycle, `src/renpy_story_mapper/storage.py:111`.

`initialize_database()` commits each schema version in a separate transaction. Injecting a v5
migration failure while opening v3 leaves the live project committed at v4 instead of rolling the
whole v3-to-v5 operation back. A backup is created by `Project.open`, but the original database is
still partially migrated and is not restored automatically. This fails the requested atomic
migration/rollback contract.

Reproduction: run `test_v3_to_v5_migration_rolls_back_as_one_atomic_unit` with `--runxfail`.
After the injected failure, `PRAGMA user_version` is `4`; expected `3`.

### P1-6 — Persistent-region analysis has quadratic whole-graph work and output

Owner: control-flow analysis, `src/renpy_story_mapper/control_flow.py:1170` and `:1370`.

Every eligible `if`/`menu` split runs `_arm_members`. For non-reconvergent nested splits, each arm
walk retains the entire downstream graph, producing quadratic traversal and quadratic persisted
`node_ids`. The integrated 10k harness has no `if` or `menu` node and therefore creates zero
regions; it does not exercise the acceptance-critical path.

The review fixture with only 400 nodes/399 edges produced 39,999 retained arm memberships (the
linear safety bound in the review test is 3,200). Separate measured runs showed:

| Nodes | Edges | Regions | Elapsed | Traced peak |
|---:|---:|---:|---:|---:|
| 500 | 499 | 249 | 0.579 s | 12.17 MiB |
| 1,000 | 999 | 499 | 2.968 s | 47.55 MiB |
| 2,000 | 1,999 | 999 | 19.294 s | 188.00 MiB |

The 2,000-node case already exceeds the 2-second target and approaches the 256 MiB ceiling. A
10,000-node version of this same control shape is not safe to run without an external memory cap.

Reproduction: run
`test_persistent_region_analysis_has_bounded_total_arm_membership` with `--runxfail`.

### P2-1 — Vendored Unrpyc version metadata does not match the pinned commit

Owner: recovery supply-chain metadata,
`src/renpy_story_mapper/ingestion/runtime.py:32` and
`src/renpy_story_mapper/ingestion/_vendor/unrpyc/PIN.json:24`.

The bundle records version `2.0.3` and commit
`3ae8334ed71a05535927dcc559663d3aca51215b`. A clean checkout of the upstream repository proves
that exact commit is tagged `v2.0.4`; upstream `v2.0.3` resolves to
`b6cfa8e9732e0565ae149fcab6ca851b60600c5a`. Six vendored Python modules match the pinned commit
after LF normalization; `decompiler/__init__.py` is intentionally reduced to remove testcase and
AST-dump imports/dispatch, but that local patch is not declared in `PIN.json`.

The complete upstream `LICENSE` matches the shipped `LICENSE.txt` after LF normalization. The
curated bundle hash verifies locally.

### P0 and P3

No P0 finding was identified. No separate P3 finding is reported; lower-severity limitations are
listed below.

## Positive evidence

- Four-tier precedence, identical same-tier deduplication, and conflicting same-tier ambiguity
  work for the tested loose/archive combinations.
- The existing RPA reader retains restrictive index unpickling and compressed/decompressed,
  entry, aggregate, and chunk bounds. No UnRPA code is shipped or invoked.
- Modern `RENPY RPC2` recovery uses the safe fake-class unpickler after bounded zlib decoding;
  Python-2-era and malformed inputs fail explicitly.
- The helper is created suspended, assigned to a kill-on-close one-process Job Object, memory
  bounded, then resumed. Timeout, cancellation, output, log, and decompression bounds passed the
  integrated tests.
- Export requires a new destination outside the resolved source/project boundary and writes
  reconstructed-evidence warnings, hashes, and provenance.
- The vendored wheel contains the license, `PIN.json`, six curated decompiler modules, and the
  third-party notice. It contains no UnRPA, upstream CLI/injector, deobfuscator, translation
  helper, testcase decompiler, AST dumper, tests, or `un.rpyc` artifact.
- Deterministic reopen, nested/bypass/long-detour, loop, irreducible-SCC, terminal, unresolved,
  state-lineage, quotient-evidence, and permutation-stability baseline tests pass.

## Security limitations

- The helper is a bounded process, not a Windows AppContainer or restricted-token sandbox.
- The child inherits the parent environment and the audit hook does not enforce filesystem
  read/write containment (P1-4).
- Cache entries are content-addressed and hash checked, but cache provenance JSON is trusted from
  the same-user cache directory and is not size-bounded before parsing.
- Files are path-checked before use rather than opened through durable directory handles; reparse
  and time-of-check/time-of-use races remain possible. The directly reproduced archive-symlink
  escape is P1-3.
- Recovery supports only modern `RENPY RPC2`; ancient, obfuscated, or modified formats remain an
  explicit unsupported limitation, as intended.

## Performance evidence

The integrated linear 10k/15k-shaped harness completed successfully:

```text
nodes=10000 edges=14998 elapsed_seconds=1.442052
traced_peak_delta_bytes=26526394 regions=0
canonical_sha256=aabfd35edb3e49b5651117432d712ba26db0026e395d7a70f0f1af788c4d8bae
```

Because it produces zero regions, it does not refute P1-6. The adversarial persistent-split
measurements above exercise the actual whole-graph-per-region path.

## Verification commands and results

All commands used Windows CPython 3.12.10 at the required interpreter path with `PYTHONPATH`
pointing to this worktree's `src` where applicable.

```powershell
& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m pytest
# 371 collected: 365 passed, 6 xfailed (review defects) in 22.92 s.

& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m pytest `
  tests/test_m06_security_review.py --runxfail -q
# Six intentional failures reproduce P1-1 through P1-6.

& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m ruff check src tests scripts
# All checks passed.

& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m mypy src\renpy_story_mapper
# Success: no issues found in 42 source files.

& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m pip check
# No broken requirements found.

git diff --check
# Passed with no output.

& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m pip wheel . --no-deps `
  --wheel-dir <temporary-directory>
# Built renpy_story_mapper-0.1.0-py3-none-any.whl; 59 members; curated runtime and notices present;
# forbidden runtime paths absent.
```

The upstream pin was verified from a clean temporary clone using `git checkout
3ae8334ed71a05535927dcc559663d3aca51215b`, `git tag --points-at HEAD`, normalized file
comparisons, and `git rev-parse 'v2.0.3^{}'`.

## Required disposition

Return P1-1 and P1-2 to the UI/organization owner, P1-3 and P1-4 plus P2-1 to the ingestion/recovery
owner, P1-5 to the storage owner, and P1-6 to the control-flow owner. M06 should not ship until the
six review regressions pass without `xfail`, the pin metadata/patch declaration is corrected, and
the full Windows acceptance suite is rerun.
