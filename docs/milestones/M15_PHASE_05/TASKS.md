# M15.1 Phase 05 task ledger

Baseline: merged `main` at `268d30ed15d50136be5a88d464f79adaf7f32f9e`

| Task | Owner | Scope / affected area | Dependencies | Status | Evidence / handoff |
|---|---|---|---|---|---|
| Contract correction | Orchestra | Replace the false 425/425 whole-game assumption; allow trusted Ren'Py use only on disposable copies | User approval | Complete | Revised `GOAL.md`, `MASTER_PLAN.md`, and current project pointer |
| Semantic review | `/root/phase05_extraction_semantic_review`, Sol/High | Check the extraction-first scope, authority split, exclusions, and lean evidence | Corrected contract | Complete | Exact head `17f8400`; `PASS`, P0=P1=P2=0 |
| Ren'Py input/runtime proof | `/root/renpy_runtime_probe` plus Orchestra | Locate matching SDK and game inputs; determine full-project versus lone-script fidelity; prepare disposable-copy command | Semantic `PASS` | Complete | Bundled Ren'Py 8.5.3 ran Day 1 and matching full archives from disposable project roots; originals matched before/after; sanitized evidence under `output/m15-phase05-renpy-probe-20260728-124621` |
| Missing-slice parser proof | `/root/known_label_probe` plus `/root/flat_recovery_parser` | Identify one omitted real label, correct the smallest parser seam, compare against Ren'Py | Semantic `PASS` and runtime proof | Complete | Commit `9d496e5`; Python and Ren'Py both report 305 source statements for the known omitted label, with matching structure and zero diagnostics |
| Local coverage grade | `/root/coverage_grade_transport` plus Orchestra | Reuse loopback transport for exact four-grade audit; prove real `PASS` and missing-item non-PASS | Corrected slice | Complete | Commit `9d496e5`; real audit `PASS`, one-choice-removed audit `PARTIAL`, 180,037 total input tokens, and zero cloud calls; exact counts/hashes in `coverage-audit.json` |
| Codex CLI contract delta | Orchestra plus one Sol/High reviewer | Record explicit Codex summary consent, keep local extraction audit, and isolate refusals for later local handling | User direction | In progress | Replaces local summary generation only; no new workflow/schema and no automatic fallback |
| Full regeneration and reader check | `/root/full_reextract_path`, `/root/whole_game_coverage_batch`, then at most two implementation workers plus Orchestra | Re-extract whole game, regenerate summaries/groups through Codex CLI, isolate refusals, reuse current grouped reader, inspect real result | Coverage `PASS` and Codex delta `PASS` | In progress | Fresh authority has 149 substantive Python labels and zero diagnostics; large-context preview target is 103 mapping jobs plus 7 editorial calls |
| Integration and PR readiness | Orchestra plus one final Sol/High reviewer | Focused/integrated checks, browser acceptance, final review, Release, push, sharded CI, PR | Useful regenerated result | Pending | No merge without explicit user approval |

Use only factual statuses: `Pending`, `In progress`, `Blocked`, or `Complete`.

Every new worker/reviewer uses explicit `gpt-5.6-sol` with High reasoning. No new Ultra task is
allowed. The task API exposes no fast-mode selector, so fast mode is unavailable/unverified.
