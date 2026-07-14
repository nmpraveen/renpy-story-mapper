# M10.1 final hardening completion report

## Completion status

Implementation and validation are complete on `codex/m10-final-hardening`. No pull request has
been created.

- Baseline: `7fd1604147afad2fa40a24c942dbe575aaef0f17`
- Full Windows suite: 603 passed
- Focused M10 suite: 56 passed
- Review gate: wait for explicit approval before creating the corrective pull request

PR #18 remains intact. This work does not revert M10, reset to M09, rewrite history, or begin
M11-M14.

## Completed correction work

- Preserved ordered predicate source/origin/kind/order/polarity/requirement provenance for
  `if`/`elif`/fallthrough and conditional menus.
- Propagated bounded temporary, persistent, and nested guard dependencies through M06 ownership,
  stopping temporary guards at proven merges and preserving unguarded alternate reachability.
- Corrected edge reachability so a live target reached elsewhere cannot make a dead or guarded
  source edge proven reachable.
- Replaced duplicated root-to-node paths with ordered constant-size predecessor witnesses and
  documented that proof input order participates in identity.
- Made simplified-view search scan canonical authority and switch to exact canonical inspection
  for suppressions without a visible representative.
- Added coherent unchanged-refresh reuse across unified, folder, and archive entry points, with
  explicit `reused_phases`, no expensive phase calls, and no staging backup on valid reuse.
- Removed the private harness's Qt-backed provider import and added headless/provider/network bombs.
- Corrected the stale AI-default toast and restored the M11-M14 roadmap.
- Added repeatable persisted scale acceptance and expanded private reporting with payload/database
  sizes, canonical timing, unchanged timing, and reused phases.

## Reviewable commits

| Commit | Purpose |
|---|---|
| `dc55407` | Branch predicates, bounded guard propagation, and edge reachability |
| `db304b0` | Linear predecessor proof provenance and scale regression |
| `407e452` | Whole-canonical search from simplified inspection |
| `3c860c2` | Coherent unchanged phase reuse without backup/writes |
| `test/docs(m10): validate scale and restore the milestone roadmap` | Acceptance harnesses, UI wording, proof contract, roadmap, and final reports |

## Final acceptance summary

- Full pytest: 603 passed in 65.18 seconds.
- Focused M10 pytest: 56 passed in 7.37 seconds.
- Ruff, strict mypy, `pip check`, four Node syntax checks, isolated wheel build/install/import, and
  `git diff --check` passed.
- Browser acceptance passed at 100% and 200%, including exact suppressed canonical detail.
- The 2,000-statement persisted scale fixture produced 8,005 proof inputs, 6,255,798 canonical
  bytes, and a 13,201,408-byte SQLite project.
- Private actual-folder acceptance passed in 28.910 seconds. Its unchanged refresh took 0.805
  seconds, reused all nine deterministic phases under fail-fast bombs, and preserved inputs.
- Private canonical/simplified payloads were 36,537,547 / 1,800,115 bytes; the SQLite project was
  110,247,936 bytes; provider constructions and remote requests were both zero.

Exact commands, before/after measurements, hashes, artifact directories, regression evidence,
known limitations, and the proposed PR title/body are authoritative in `VALIDATION_REPORT.md`.

## Roadmap and limitations

- M11 owns human story scenes and scene/chapter presentation.
- M12 owns route-to-target solving and path requirements.
- M13 owns the optional AI narrative layer: titles, summaries, characters, motives, and
  chapter/route/full-plot summaries.
- M14 owns dynamic framework adapters and optional runtime tracing and is deferred indefinitely.

M10 remains conservative for creator Python, dynamic transfers, and arbitrary satisfiability.
Search/result materialization and rendering remain bounded. Pre-metadata projects require one full
refresh before no-write reuse can be proven.

## Proposed pull request

Title: `Harden M10 guarded reachability, canonical search, and unchanged refresh`

Use the full proposed body in `VALIDATION_REPORT.md`. Stop here and wait for explicit approval; do
not create the pull request from this report alone.
