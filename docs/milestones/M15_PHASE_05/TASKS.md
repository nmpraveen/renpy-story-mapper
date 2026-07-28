# M15.1 Phase 05 task ledger

Baseline: merged `main` at `268d30ed15d50136be5a88d464f79adaf7f32f9e`

| Task | Owner | Scope / affected area | Dependencies | Status | Evidence / handoff |
|---|---|---|---|---|---|
| Contract correction | Orchestra | Replace the false 425/425 whole-game assumption; allow trusted Ren'Py use only on disposable copies | User approval | Complete | Revised `GOAL.md`, `MASTER_PLAN.md`, and current project pointer |
| Semantic review | `/root/phase05_extraction_semantic_review`, Sol/High | Check the extraction-first scope, authority split, exclusions, and lean evidence | Corrected contract | Complete | Exact head `17f8400`; `PASS`, P0=P1=P2=0 |
| Ren'Py input/runtime proof | `/root/renpy_runtime_probe` plus Orchestra | Locate matching SDK and game inputs; determine full-project versus lone-script fidelity; prepare disposable-copy command | Semantic `PASS` | In progress | Matching bundled Ren'Py 8.5.3 found; CLI requires a project root containing `game/`. Day 1 is a smoke input; matching full archives are the coverage oracle. Execution pending |
| Missing-slice parser proof | `/root/known_label_probe` plus one Sol/High implementation worker | Identify one omitted real label, correct the smallest parser seam, compare against Ren'Py | Semantic `PASS` and runtime proof | Pending | No summaries or UI work until this passes |
| Local coverage grade | One Sol/High implementation worker | Reuse loopback transport for exact four-grade audit; prove real `PASS` and missing-item non-PASS | Corrected slice | Pending | Local-only; deterministic mismatches cap grade |
| Full regeneration and reader check | At most two Sol/High workers plus Orchestra | Re-extract whole game, regenerate summaries/groups, reuse current grouped reader, inspect real result | One-slice `PASS` | Pending | Old 425/24 artifacts are baseline only |
| Integration and PR readiness | Orchestra plus one final Sol/High reviewer | Focused/integrated checks, browser acceptance, final review, Release, push, sharded CI, PR | Useful regenerated result | Pending | No merge without explicit user approval |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`.

Every new worker/reviewer uses explicit `gpt-5.6-sol` with High reasoning. No new Ultra task is
allowed. The task API exposes no fast-mode selector, so fast mode is unavailable/unverified.
