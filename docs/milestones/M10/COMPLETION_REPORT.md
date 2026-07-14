# M10 post-merge hardening completion report

## Completion status

The corrective implementation and validation are complete. No pull request has been created.

- Baseline `main`: `68923e494d3c8200514845191ced683239e714fc`
- Correction branch: `codex/m10-post-merge-hardening`
- Review gate: corrected report complete; wait for explicit approval before creating the PR

M10 remains merged and intact. This branch does not revert the merge, reset to M09, rewrite
history, or start M11, M12, or M13.

## Completed correction work

- Reproduced the reported blockers in a separate regression-first commit.
- Moved canonical reachability authority to resolved M06 control flow so synthetic procedure-exit
  and return-site nodes participate in reachability.
- Added bounded deterministic proof provenance for reachability, SCC/loop membership, terminal
  classification, call-return continuation, branch-arm membership, and merge/region derivation.
- Enforced analysis-state/projection/canonical schema, generation, and canonical-hash coherence.
- Made canonical page/detail independent of simplified projection availability.
- Added typed unavailable responses with analysis generation/failure status.
- Made failed/partial create or refresh enter the best retained deterministic workspace and keep a
  persistent failure banner.
- Made current M10 simplified inspection the normal default, with current canonical, coherent
  stale M10, and M07 as ordered fallbacks.
- Added bounded whole-graph search and exact focus outside the current 30-node page.
- Added direct/linked detail for regions, facts, evidence, and proofs.
- Corrected nested-region arm traversal so enclosing-arm continuation facts remain attached after
  a nested merge.
- Added a clear opaque creator-code status: `Unsupported creator Python · preserved, not executed`.
- Persisted nonnegative completed- and failed-phase operational timing while keeping timing outside
  normalized canonical bytes.
- Added and passed a stronger private harness for actual folder ingestion, exact manifest
  counts/rejoins, condition/effect attachment, provider/network bombs, unchanged refresh reuse,
  fresh-project determinism, and input immutability.

## Reviewable commits

| Commit | Purpose |
|---|---|
| `ea55c82` | Regression-first reproduction of post-merge blockers |
| `c9e4812` | Resolved M06 reachability and deterministic proof provenance |
| `41b9d91` | Coherent generation read models and canonical-without-projection behavior |
| `d10ca96` | Retained failure results and M10 default browser selection |
| `ebc0293` | Whole-graph focus and derivation detail |
| `92b67dc` | Private/browser/synthetic acceptance, nested-arm attachment, and phase timing |
| `docs(m10): record corrected validation` | Contract/completion/validation alignment; exact hash is supplied in the final handoff |

The regression-first history remains separate and reviewable.

## Validation handoff

The corrected validation report records 590 passing repository tests, 43 focused M10 tests,
passing Ruff/strict-mypy/dependency/package/JavaScript checks, and real-browser acceptance at 100%
and 200%. Private actual-folder acceptance passed 4 choices, 8 arms, 4 exact rejoins, 5
conditions, 9 effects, 52-source refresh reuse, fresh replay determinism, input immutability, and
measured zero provider constructions/remote requests. No unrun result is claimed.

## Known limitations

- Unsupported creator Python is preserved but not executed.
- Dynamic transfers remain unresolved when deterministic analysis cannot establish their targets.
- Reachability does not prove arbitrary expression satisfiability and remains conservative in an
  open world.
- A failed new simplified projection is unavailable rather than being paired with a different
  canonical generation.
- The simplified inspection is structural, not a human scene/chapter model.
- Dense graphs retain bounded paging and rendering limits.
- The private folder's 52 authoritative sources plus 5 secondary extras produce 418 simplified
  records; the exact manifest source produces 68 within its unchanged 100-record bound. M10 pages
  remain bounded to 30 nodes/180 edges.
- Day/chapter inference and numbered-name/asset-name heuristics are not added.

## Explicit deferrals

- M11 owns human narrative organization and semantic scene/chapter presentation.
- M12 owns route-to-target solving and path feasibility.
- M13 owns dynamic framework expansion and optional runtime trace validation.

## Proposed corrective pull request

Title:

`Harden M10 generation integrity, inspection provenance, and acceptance`

Body:

> Correct M10's resolved reachability and proof provenance, make canonical/simplified reads
> generation coherent, expose retained failure results, default to M10 inspection, add bounded
> whole-graph search and derivation detail, persist operational phase timing, and strengthen private
> acceptance around actual ingestion, exact source-known rejoins, refresh reuse, determinism,
> immutability, and fail-fast provider/network boundaries.
>
> Validation: 590 repository tests, 43 focused M10 tests, all static/package checks, browser 100% /
> 200%, and actual-folder private acceptance passed. The corrected validation report contains the
> exact timings, hashes, counts, and artifact paths.
>
> Boundaries: no M10 revert, M09 reset, history rewrite, or M11/M12/M13 work.

## Stop condition

The corrected validation report contains measured results for every required check. Stop and wait
for explicit approval. Do not create the corrective pull request from this report alone.
