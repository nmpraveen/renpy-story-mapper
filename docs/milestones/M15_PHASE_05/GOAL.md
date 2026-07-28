# M15.1 Phase 05 - Whole-story extraction and readable timeline

Status: In progress (one-slice Ren'Py extraction gate)

Scope authority: `docs/MASTER_PLAN.md`, M15 / M15.1 semantic Story Map correction

Planning authority: `docs/MILESTONE_PLANNING_RULES.md`

## Simplicity rule

Fix the demonstrated missing-story input first. Use Ren'Py only where it is the smallest reliable
way to understand the trusted current game, keep Python responsible for the story graph, and do
not regenerate summaries or change the reader until one real missing slice passes.

## Done condition

Opening the MsDenvers project shows a clean chronological vertical timeline that represents the
whole parsed game rather than only the old 425-section projection. Important choices, branch
outcomes, routes, state changes, rejoins, and endings are easy to follow while scrolling. A
matching Ren'Py SDK checks the trusted game from a disposable copy, Python builds the deterministic
story structure, and local-only AI both audits extraction coverage and organizes the readable
story prose.

## Objective

Recover the story content omitted before the 24-group timeline was built, prove the correction on
one small real-game slice, then regenerate and reuse the existing grouped reader only if that proof
succeeds.

## Must work now

- Determine whether the matching Ren'Py SDK needs the complete game project or can faithfully use
  one script. Prefer the smallest input that preserves the game's real labels, dialogue, menus,
  jumps, calls, and custom statements.
- Run Ren'Py only against a disposable copy of the trusted input. The supplied original game
  folder, scripts, and archive remain read-only and are fingerprinted before and after the proof.
- On one known missing real-game label or similarly small slice, compare Ren'Py's label,
  dialogue/menu, and structural output with the existing Python extraction. Correct the smallest
  demonstrated Python omission; if one focused correction is insufficient, use a tiny temporary
  Ren'Py AST exporter on the disposable copy instead of repeatedly expanding the parser.
- Send the source/Ren'Py/Python comparison only to the configured loopback local model. Its audit
  result is exactly one of `PASS`, `PARTIAL`, `LOW`, or `FAIL`. Deterministic missing-content facts
  cap the grade; AI may lower but never raise that evidence-based ceiling.
- Only after the slice earns `PASS`, rerun the affected extraction, local summaries, editorial
  grouping, and the existing scrolling reader. The old 425 summaries and 24 groups are reusable
  implementation inputs, not authoritative whole-game coverage.

## Useful later

- Broader support for unrelated Ren'Py versions or unusual third-party frameworks.
- Human-edited day/chapter names where the game has no authoritative hierarchy.
- Exact imitation of an old mock's colors and broader visual polish.

## Do not build in this milestone

- A new database, migration, scheduler, workflow, API version, schema family, or recovery system.
- A general Ren'Py compatibility framework, SDK installer, or version-adapter matrix.
- Cloud story-content AI or automatic local-model installation/loading.
- A freeform graph canvas, formal proof system, exhaustive semantic replay, or
  publication-grade prose guarantees.
- AI-invented mechanics or game-specific hard-coded day assumptions.
- Broad UI or summary work before the one-slice extraction gate passes.

## Acceptance criteria

1. A focused experiment records whether a full game project or lone script is the faithful Ren'Py
   input for this game, and all Ren'Py-created files stay inside a disposable working copy.
2. For one real slice that the old projection missed, Ren'Py reports substantive story content and
   Python reports matching labels plus substantive dialogue/menu/structure instead of an empty
   shell.
3. The loopback local-AI audit returns exactly `PASS`, `PARTIAL`, `LOW`, or `FAIL`; the corrected
   real slice returns `PASS`, while an in-memory comparison with one material item removed cannot
   return `PASS`.
4. After criteria 1-3 pass, the full current game is re-extracted and regenerated without treating
   425/425 as a frozen target; deterministic coverage diagnostics and the AI audit identify any
   remaining incomplete areas before publication.
5. The regenerated project opens as a readable whole-story vertical timeline with visible
   choices/routes/rejoins and direct Detail/Evidence access; focused checks, one integrated Story
   Map gate, final review, sharded PR CI, and one final Windows Release/package gate pass while
   original inputs remain unchanged and story content remains local.

## Required evidence

| Criterion | Evidence required | Result / durable location |
|---|---|---|
| 1 | SDK/version discovery, input comparison, disposable-copy path, and original-input fingerprints | Discovery: the trusted distribution bundles matching Ren'Py 8.5.3; its CLI requires a project root with `game/`, not a lone `.rpy` argument. Disposable-copy execution and before/after fingerprints are pending |
| 2 | One label-sized Ren'Py/Python comparison with private prose omitted from reports | Pending |
| 3 | Local-only audit transcript/receipt for the real and deliberately incomplete comparisons | Pending |
| 4 | Full-game extraction counts, coverage grades, and regenerated artifact identity | Pending; blocked on criteria 1-3 |
| 5 | Current browser walkthrough/screenshots plus focused, integrated, review, CI, and Release results | Pending; blocked on criterion 4 |

## Superseded evidence

- Generation `5daf4e7e...bab7857` exactly covers all 425 previously accepted sections in 24 groups,
  but this proves only projection coverage. It does not prove whole-game narrative coverage because
  substantial later-game sources were parsed as empty label shells.
- The existing grouped reader, path rail, and Detail/Evidence work remain useful and should be
  reused after extraction is corrected.

## Exclusions

- No promise that the game contains authoritative Day 1/Day 2 names.
- No cloud provider call or transmission of private story content.
- No broad cleanup merely because existing Phase 04/05 code is complex.
- No writes to the supplied original game folder/archive and no merge without separate explicit
  user approval.

## Dispatch settings

- Orchestra: this user-visible task; its runtime model and fast-mode state are not exposed here and
  are not claimed.
- Every new worker and reviewer uses explicit `gpt-5.6-sol` with High reasoning. No new Ultra task
  is allowed. The task API exposes no fast-mode selector, so fast mode is unavailable/unverified.
- One Orchestra and at most two concurrent workers. Use one early semantic review and one final
  integrated review by default.

## Handoff rules

- Stop at the one-slice proof and report the result before broad regeneration if it does not earn
  `PASS` or reveals a materially different architecture choice.
- Prefer Ren'Py's built-in `lint`, `dialogue`, and label inventory first. Add one temporary
  no-display AST exporter only if the built-ins cannot prove the slice.
- Reuse the existing Python graph, loopback transport, reader/API shapes, and grouped UI; pause
  before any new contract family.
- Run affected checks while editing, one focused integration gate, sharded CI once at the PR
  candidate, and one final Release/package gate.
- Keep the native Codex goal active through implementation, integration, verification, user
  acceptance, and PR preparation. Complete it only when the PR is genuinely ready.
