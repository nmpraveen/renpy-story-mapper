# M06 Independent Security, Compatibility, and Correctness Review

Review date: 2026-07-12

Reviewer branch: `codex/m06-security-review`

Integrated base reviewed: `f64c8ef241f0773d43f03cab71c52f101ae8dc6b`

Production diff reviewed: `3125743..f64c8ef`

## Initial recommendation (superseded)

**NO-SHIP at `f64c8ef`.** The integrated implementation had six independently reproduced P1 defects and one
P2 supply-chain metadata defect. The positive baseline suite remains green because the review
regressions are retained as strict expected failures; running them with `--runxfail` reproduces
all six implementation failures.

This historical recommendation is superseded by the final closure at the end of this report.

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

## Final resolution re-review — 2026-07-12

Verification target: `C:\Users\prave\Documents\Codex\Renpy`

Target branch: `codex/m06-safe-ingestion-route-semantics`

Exact target commit: `ee87c31cf88ebb167ed28af973025af7d440307d`

This final pass inspected the actual remediation commits `5b3837b`, `553c180`, `848b3c6`, and
`ee87c31`, including the integrated review tests, without modifying the orchestrator checkout.
The six original P1 findings and original P2 pin-metadata finding are resolved. One separate P2
procedure-summary correctness finding remains, so the final recommendation is still **NO-SHIP**.

### Original finding resolution mapping

| Original finding | Resolution evidence | Final status |
|---|---|---|
| P1-1 incomplete recovery did not block cloud organization | `553c180` checks persisted coverage before provider construction; `ee87c31` retains compatibility with test project doubles | Resolved |
| P1-2 desktop bypassed unified ingestion | `5b3837b` routes create/refresh through `create_ingested_project` and `refresh_ingested_project`, accepts `.rpy`, `.rpyc`, `.rpa`, and folders | Resolved |
| P1-3 archive symlink escaped the selected game root | `553c180` resolves every discovered archive and requires containment under `source_root` | Resolved |
| P1-4 helper inherited ambient environment and allowed outside writes | `553c180` supplies a minimal environment and restricts audit-hook reads/writes to explicit roots | Resolved, subject to the AppContainer limitation below |
| P1-5 v3-to-v5 migration was only version-atomic | `553c180` wraps the complete migration and v4 extension in one transaction | Resolved |
| P1-6 persistent-region analysis was quadratic | `848b3c6` adds one SCC-condensation reachability pass, bounded terminal samples, and direct-membership traversal that stops at nested region boundaries; `ee87c31` makes the review regression mandatory | Resolved |
| P2-1 Unrpyc version metadata conflicted with the pinned commit | `553c180` records tag `v2.0.4` separately from upstream internal string `2.0.3` | Resolved |

All six formerly expected-failure reproductions now pass as ordinary tests:

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path
& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m pytest `
  tests/test_m06_security_review.py -q
# 6 passed in 0.20s
```

### Remaining P2 — non-returning calls are persisted as procedure termination

Owner: control-flow procedure summaries,
`src/renpy_story_mapper/control_flow.py:575-609`, specifically the `goal == "terminate"` shortcut
at lines 606-608.

`_procedure_reaches(..., goal="terminate")` returns `True` whenever a call target has
`may_return=False`. That conflates divergence/non-returning behavior with concrete termination.
The integrated fixture proves the inconsistency:

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path
@'
import runpy
ns = runpy.run_path('tests/test_m06_control_flow.py')
for entry in ('recursive', 'never_returns', 'calls_never_returns'):
    _, analysis = ns['analyze_fixture']('calls_loops.rpy', entry=entry)
    procedure = next(item for item in analysis.procedures if item.label == entry)
    print(entry, procedure.may_return, procedure.may_terminate, procedure.recursive,
          procedure.looping)
'@ | & 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -
```

Observed:

```text
recursive may_return=False may_terminate=True recursive=True looping=True
never_returns may_return=False may_terminate=False recursive=False looping=True
calls_never_returns may_return=False may_terminate=True recursive=False looping=False
```

`recursive` and `calls_never_returns` cannot reach a `module_end`; they only enter non-returning
recursion/a loop. Persisting `may_terminate=True` can incorrectly turn divergence into ending
evidence for later route presentation. This is a P2 correctness issue because it affects an
authoritative schema-v5 procedure fact, although no current M06 consumer uses the field to create
an edge.

No P0, P1, or P3 finding remains. The remaining count is one P2.

### Call-summary and return-site invariant

The call-summary abstraction is acceptable and is not the remaining finding. It deliberately
avoids the M01 caller/return cross product:

- a `CALL_SUMMARY` exists only when the callee may return;
- every returning call owns one unique synthetic return site;
- summary evidence is exactly the ordered `call`, `call_continuation` pair;
- the synthetic return edge retains only its own `call_continuation` evidence; and
- raw callee `return` evidence stays on the procedure return boundary and is never attributed to a
  caller-specific summary.

Measured fixture result: two summaries, two caller-specific return edges, unique call-site and
return-site identities, and zero raw-return evidence in summaries. The focused call, recursion,
non-returning-call, and performance checks passed: `4 passed in 0.70s`.

### Final performance measurements

The required Windows CPython 3.12 inline harness measured both graph shapes with `tracemalloc` and
SHA-256 of canonical analysis output:

| Harness | Nodes | Edges | Regions | Arm membership | Elapsed | Traced peak delta | Canonical SHA-256 |
|---|---:|---:|---:|---:|---:|---:|---|
| Linear 10k/15k | 10,000 | 14,998 | 0 | 0 | 1.373648 s | 26,526,210 bytes | `aabfd35edb3e49b5651117432d712ba26db0026e395d7a70f0f1af788c4d8bae` |
| Persistent split chain | 2,000 | 1,999 | 999 | 1,998 | 0.484187 s | 5,102,593 bytes | `4a4a3bd38744a457e75eae9913b8c290680b4b2ede9213819c303f80cbd96d4f` |

The formerly quadratic 2,000-node shape improved from 19.294 seconds/188.00 MiB to 0.484187
seconds/4.87 MiB traced peak. Both target limits pass with substantial margin.

### Environment, pin, wheel, and security verification

The helper environment contains only:

```text
SYSTEMROOT, WINDIR, TEMP, TMP, PYTHONHASHSEED, PYTHONIOENCODING,
PYTHONNOUSERSITE, PYTHONUTF8
```

`TEMP` and `TMP` point to the private helper work directory. `PATH`, `PYTHONPATH`, `USERPROFILE`,
`HOME`, `OPENAI_API_KEY`, and `CODEX_HOME` are absent. The audit policy permits writes only below
the private work root and reads only below the private work root, curated vendor root, or standard
library root.

The metadata verification command and result were:

```powershell
git ls-remote --tags https://github.com/CensoredUsername/unrpyc.git `
  refs/tags/v2.0.3 refs/tags/v2.0.4
# b6cfa8e9732e0565ae149fcab6ca851b60600c5a  refs/tags/v2.0.3
# 3ae8334ed71a05535927dcc559663d3aca51215b  refs/tags/v2.0.4
```

At pinned commit `3ae8334`, upstream `unrpyc.py` still contains internal
`__version__ = 'v2.0.3'`; the shipped metadata now truthfully distinguishes that internal string
from the `v2.0.4` tag. The two focused pin/environment tests passed in `0.06s`.

The wheel was built and inspected with:

```powershell
& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m pip wheel . `
  --no-deps --wheel-dir <temporary-directory>
```

Result: `renpy_story_mapper-0.1.0-py3-none-any.whl`, 249,237 bytes, 59 members, wheel SHA-256
`a422d571a06cd04db4601850507d1f668f6502600c020db8e29a672c6612090c`. Recomputed curated
bundle SHA-256 exactly matched
`fb764521f9d3120b0c62198f086226f837802d73eccc9cad3c2ad683b1117775`. License, `PIN.json`, six
curated runtime modules, and `THIRD_PARTY_NOTICES.md` were present. No UnRPA, injector,
`unrpyc.py`, deobfuscator, translation helper, testcase decompiler, AST dumper, testcases, or
`un.rpyc` artifact was present.

The helper remains a Job Object plus Python audit-policy isolation boundary, not a Windows
AppContainer or restricted-token sandbox. This is the remaining documented security limitation,
not a new P0-P3 finding: the child is suspended before Job assignment, process/memory/time/output
bounds remain enforced, the environment is sanitized, and filesystem policy is now explicit.

### Final verification matrix

All commands below ran in the clean orchestrator checkout at exact commit `ee87c31` using Windows
CPython 3.12.10:

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path

& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m pytest
# 374 passed in 19.57s

& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m ruff check src tests scripts
# All checks passed!

& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m mypy src\renpy_story_mapper
# Success: no issues found in 42 source files

& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m pip check
# No broken requirements found.

git diff --check
git diff --check f64c8ef..ee87c31
# Both passed with no output; the orchestrator worktree remained clean.
```

No canonical or MsDenvers archive was accessed, and no cloud AI was run.

### Re-review recommendation at `ee87c31` (superseded)

**NO-SHIP at `ee87c31`.** All original review findings are resolved and the security/performance
remediations pass, but M06 acceptance requires no remaining P0-P3 correctness/security finding.
Correct the `may_terminate` treatment of non-returning/diverging calls, add a regression that
distinguishes termination from divergence, and rerun the Windows matrix. No other P0-P3 issue was
found in this final re-review.

## Final closure — 2026-07-12

Final verification target: `C:\Users\prave\Documents\Codex\Renpy`

Final target branch: `codex/m06-safe-ingestion-route-semantics`

Exact final target commit: `eb850dca4ccb73e7f3334c03f8837331467f7368`

Commit `eb850dc` replaces the incorrect shortcut that treated every non-returning callee as a
concrete termination. Procedure termination is now a separate fixed-point fact propagated only
from concrete terminating procedures or terminating tail jumps. The orchestrator checkout was
inspected and verified without modification.

### P2 closure evidence

The corrected procedure summaries satisfy every requested case:

| Procedure shape | `may_return` | `may_terminate` | Result |
|---|---:|---:|---|
| Helper with explicit return | true | false | Caller continuation remains possible |
| Caller of returning helper with explicit return | true | false | Return propagates through caller |
| Infinite self-jump | false | false | Divergence is not termination |
| Caller of infinite self-jump | false | false | Non-returning callee does not create termination |
| Concrete ending | false | true | Concrete termination is recognized |
| Caller of concrete ending | false | true | Termination propagates through caller |
| Unbounded recursive call | false | false | Recursive behavior remains conservative |
| Dynamic/unresolved call | false | false | Unresolved behavior remains conservative |

Focused production and integrated-review command:

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path
& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m pytest `
  tests/test_m06_control_flow.py::test_procedure_termination_fixed_point_distinguishes_divergence `
  tests/test_m06_control_flow.py::test_unresolved_call_does_not_become_concrete_termination `
  tests/test_m06_control_flow.py::test_calls_use_call_site_correct_return_sites_without_cross_product `
  tests/test_m06_control_flow.py::test_control_flow_is_persisted_and_reopens_canonically `
  tests/test_m06_security_review.py -q
# 10 passed in 0.28s
```

A separate fresh temporary schema-v5 project combined returning, infinite, terminating,
recursive, and unresolved procedures. Its authoritative `m06_control_flow` payload was identical
before and after `Project.open()`. Persisted flags matched the table above, recursion and unresolved
diagnostics remained conservative, and the canonical reopened payload SHA-256 was
`91245e2c5261a118e1b48d7b1448d5a8012791d59d8649d1d0b33109631c7605`.

The caller-specific call-summary invariant remains accepted: returning callees get unique
synthetic return sites and continuation evidence; non-returning callees get no false continuation;
raw callee return evidence remains procedure-scoped rather than multiplied across callers.

### Final scale gates

The same Windows CPython 3.12 `tracemalloc` harness used in the preceding review produced:

| Harness | Nodes | Edges | Regions | Arm membership | Elapsed | Traced peak delta | Canonical SHA-256 |
|---|---:|---:|---:|---:|---:|---:|---|
| Linear 10k/15k | 10,000 | 14,998 | 0 | 0 | 1.418960 s | 26,526,210 bytes | `aabfd35edb3e49b5651117432d712ba26db0026e395d7a70f0f1af788c4d8bae` |
| Persistent split chain | 2,000 | 1,999 | 999 | 1,998 | 0.495679 s | 5,102,817 bytes | `4a4a3bd38744a457e75eae9913b8c290680b4b2ede9213819c303f80cbd96d4f` |

Both gates remain comfortably below two seconds and 256 MiB additional traced memory.

### Final acceptance matrix

All commands ran in the clean orchestrator checkout at exact commit `eb850dc`:

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path

& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m pytest
# 376 passed in 20.25s

& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m ruff check src tests scripts
# All checks passed!

& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m mypy src\renpy_story_mapper
# Success: no issues found in 42 source files

& 'C:\Users\prave\Documents\Codex\Renpy\.venv\Scripts\python.exe' -m pip check
# No broken requirements found.

git diff --check
git diff --check ee87c31..eb850dc
# Both passed with no output; the orchestrator worktree remained clean.
```

No canonical or MsDenvers archive was accessed, and no cloud AI was run.

### Non-blocking packaging limitation

The recovery helper remains a suspended process constrained by a kill-on-close Job Object,
sanitized environment, explicit filesystem audit policy, and time/memory/process/output bounds. It
is not a Windows AppContainer or restricted-token sandbox. That remains an explicit packaging and
defense-in-depth limitation, but it is non-blocking for the current M06 source-form deliverable.

### Final recommendation

**SHIP for the M06 source-form deliverable at `eb850dc`.** No P0, P1, P2, or P3 correctness or
security finding remains. The AppContainer/restricted-token packaging limitation must remain
documented and should be revisited before any future packaged or publicly distributed build.
