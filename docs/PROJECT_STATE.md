# Ren'Py Story Mapper project state

Updated: 2026-07-26 (M15.1 Phase 04 Tracks A and B passed exact-head review and PR CI and are
integrated at `24e6ea8`; their product seam is frozen, repository-wide CI acceleration and
Tracks C/D are the next parallel work, the native goal remains active, and the lifecycle is
`In progress`)

`docs/MASTER_PLAN.md` owns product scope. This file owns the operational pointer to one explicit milestone contract. Milestone-local files own acceptance and evidence.

## Current contract

- Active milestone: M15.1 Phase 04 full-game scaling, persistence, recovery, and product workflow.
- Active contract: [`docs/milestones/M15_PHASE_04/GOAL.md`](milestones/M15_PHASE_04/GOAL.md).
- Active design: [`docs/milestones/M15_PHASE_04/PHASE_04_DESIGN.md`](milestones/M15_PHASE_04/PHASE_04_DESIGN.md).
- Integration baseline: synchronized `main`/`origin/main` at Phase 03 closeout merge
  `e715d8ae80dd1188c729a447cfabf3c45b3b7286`.
- Integration branch: `codex/m15-phase04-full-game`.
- Current integrated A/B checkpoint: `24e6ea8` (Track PRs #31 and #32 merged normally into the
  Phase 04 integration branch). A/B interfaces are frozen for Tracks C and D.
- Status: In progress.
- Merge state: Phase 03 PR #28 and closeout PR #29 are merged. Draft Phase 04
  [PR #30](https://github.com/nmpraveen/renpy-story-mapper/pull/30) is open against `main` and
  intentionally unmerged.
- Semantic review: repeated exact-head `PASS` at corrected checkpoint
  `eb1d2672b76d1445a2dbbb770b1d2cd152d45bf2` in
  [`SEMANTIC_REVIEW.md`](milestones/M15_PHASE_04/SEMANTIC_REVIEW.md). The document preserves the
  initial `REVISE` and its corrected consent conflict; current P0=P1=P2=0.
- Native Codex goal: active on coordinator task `019f7fe2-eeaa-7622-b3eb-f53d5bd5f749`, created
  from the exact `GOAL.md` done condition after repeated semantic `PASS`. Keep it active through
  integration, verification, review, and genuine PR readiness.
- Accepted private input:
  `C:/Users/prave/Documents/Codex/Renpy/output/m15-story-map-v2-phase-02-20260724-2135/`.
  The package is complete 1/1 with 12 events, four choices, eight outcomes, zero validation
  failures, and matching source/archive/project hash, size, and timestamp. Exact Phase 02
  full-history checkpoint `a42e8a0` passed its final GitHub run before the clean Phase 03 baseline.
- Visible task settings: every track/reviewer must explicitly use `gpt-5.6-sol` with High
  reasoning. The task API has no fast-mode field, so task fast mode is unavailable/unverified.
- Phase 04 Track A Coordinator: visible task `019fa00d-1e55-79e0-95b0-c88f8fd89919`, worktree
  `C:/Users/prave/.codex/worktrees/6321/Renpy`, dispatched from exact integration checkpoint
  `9e5088ea54dcd227e933fb14884d408596ff979b` with explicit `gpt-5.6-sol` High. Worker A1 is task
  `019fa00e-c8e5-7141-8c83-d043b27d9d34` in `C:/Users/prave/.codex/worktrees/9f93/Renpy`;
  Worker A2 is task `019fa00e-c8e9-7422-bce8-adc0b692ff40` in
  `C:/Users/prave/.codex/worktrees/fe82/Renpy`; the independent reviewer is task
  `019fa00e-c967-7e71-a7e4-151e1cfcb498` in `C:/Users/prave/.codex/worktrees/ad4a/Renpy`.
- Phase 04 Track A completion: exact pushed head
  `c03222c329b23f05b574fc4c91b7e30a04d46fc1` passed independent review with
  P0=P1=P2=P3=0 and GitHub deterministic checks in 18m49s. Track
  [PR #31](https://github.com/nmpraveen/renpy-story-mapper/pull/31) merged normally into the
  Phase 04 integration branch at `b18ab4d`; a post-merge focused gate passed 25 tests. Track A is
  complete.
- Phase 04 Track B Coordinator: visible task `019fa00d-1e77-7fd3-93d5-ee9761a5f662`, worktree
  `C:/Users/prave/.codex/worktrees/bcc8/Renpy`, dispatched from the same exact checkpoint with
  explicit `gpt-5.6-sol` High. Worker B1 is task `019fa00f-8e20-7382-8dc9-2c1ce5d39975` in
  `C:/Users/prave/.codex/worktrees/d46a/Renpy`; Worker B2 is task
  `019fa00f-b94c-7af1-9b10-1b67c64ea6fb` in `C:/Users/prave/.codex/worktrees/f258/Renpy`;
  the independent reviewer is task `019fa00f-dad0-7b13-9454-9c9b44a0d098` in
  `C:/Users/prave/.codex/worktrees/70a9/Renpy`. Both coordinators report fast-mode selection as
  unavailable/unverified.
- Phase 04 Track B completion: the initial integrated candidate `0942ea8` was rejected with two
  P1 durable-authority findings. Corrected product head
  `948994e3a13c77982cb356692e1fe15b5f079147` passed independent exact-head review with
  P0=P1=P2=P3=0. A one-line stale schema-version test then caused the first PR run
  `30223104080` to fail with `1 failed, 1568 passed, 16 deselected`; exact test-only head
  `edf8b4fc95ff90803982b94b726ee810a6c67d25` independently passed review and GitHub run
  `30224335123` / job `89851989571` in 17m22s. Track
  [PR #32](https://github.com/nmpraveen/renpy-story-mapper/pull/32) merged normally into the
  integration branch at `24e6ea8`. The post-merge A/B seam gate passed 151 tests, Ruff, strict
  mypy over 118 source files, `pip check`, and diff hygiene.
- Repository-wide CI acceleration: visible coordinator task
  `019fa0a1-e213-7f62-8ca9-ea0e6e1de032`, branch `codex/m15-p4-ci-shards`, worktree
  `C:/Users/prave/.codex/worktrees/d42f/Renpy`, explicit `gpt-5.6-sol` High with fast-mode
  unavailable/unverified. It is replacing the serial Windows pytest bottleneck with complete,
  timing-balanced required shards and a stable aggregate check without dropping tests. This is a
  shared workflow improvement for all future repository PRs and `main` pushes, not a Phase 04-only
  exception. Current action: freeze and independently review that correction while Tracks C and D
  proceed from the frozen A/B product seam, then make C/D consume the accepted workflow before
  their exact pushed-head gates.
- Pull request: [#28](https://github.com/nmpraveen/renpy-story-mapper/pull/28), merged normally
  after separate explicit user approval on 2026-07-26 at
  `27035cba5c55585ea5dbeb48e6dd1cd026c44941`. Reviewed PR head was
  `1dd55ff61f20bbc75618a1cab613ac5e7c52b1ec`; its tree exactly matches the merge tree.
- Visible Track A Coordinator: task `019f9c58-e638-71a0-b6a2-cb88b72f3d24`, worktree
  `C:/Users/prave/.codex/worktrees/e7ca/Renpy`, explicit `gpt-5.6-sol` with High reasoning;
  fast-mode selection is unavailable/unverified. It started from exact contract checkpoint
  `4f6e3a6` and produced rejected review head `420dbb7`.
- Track A reviewer: visible task `019f9c67-af1c-7812-a471-1f6a98572f1c`, worktree
  `C:/Users/prave/.codex/worktrees/8255/Renpy`, initially returned `FAIL` at `420dbb7` with two
  P1s and one P3, then found one schema-file binding P2 at corrected head `62a0234`. The same
  reviewer returned final `PASS` at exact head `2319092` with P0=P1=P2=P3=0.
- Track A integration: reviewed worker commits `420dbb7`, `62a0234`, and `2319092` were
  cherry-picked byte-equivalently as `e4b497f`, `1dcc63e`, and `50bdc08`. Coordinator CPython
  3.12 focused verification passed 50 tests; the integration branch is clean apart from preserved
  untracked user/private paths.
- Track B browser: visible task `019f9c8d-cfb6-7b32-8c7f-51482bbe39c6`, worktree
  `C:/Users/prave/.codex/worktrees/9ea6/Renpy`, dispatched with explicit `gpt-5.6-sol` High from
  exact frozen checkpoint `4827b06` (Track A product seam through `50bdc08`). It owns only the
  static browser and focused tests. It completed clean exact head
  `2069eab3a1f0a018724106f94634e1292072e358` after a fresh final-byte gate covering focused/static/
  schema/lint, the desktop 100%/effective-200%/390px Chrome matrix, 63 adjacent tests, 107-file
  mypy, asset integrity, and diff hygiene. One accidentally enabled out-of-scope M13 hardware
  smoke timed out on its pre-existing selector and is excluded from Track B evidence.
- Track B reviewer: visible read-only task `019f9ca9-ab9e-77c0-a2f1-0426f9472084`, worktree
  `C:/Users/prave/.codex/worktrees/4f7b/Renpy`, explicit `gpt-5.6-sol` High, returned `FAIL /
  CHANGES REQUIRED` at exact head `2069eab3a1f0a018724106f94634e1292072e358`, P0=0, P1=0,
  P2=5, P3=0. Findings require the exact shared fixture identity, strict deeply bounded map records,
  preserved/restorable path context, visible authoritative reachability/item warnings, and honest
  unassociated witness groups. Corrected clean head `81313d7b2b86bf12c3236659f259c24f129dd00c`
  passes 10 focused/three-profile Chrome, the exact 131 pass/2 opt-in skip adjacent matrix,
  adversarial contracts, 107-file mypy, Ruff/JS/fixture/asset/diff gates. Rereview of that head
  closed all five original findings but returned `FAIL /
  CHANGES REQUIRED`, P0=0, P1=0, P2=1, P3=0 because closing the path panel did not invalidate an
  in-flight response, which could reopen it. The worker then made only the bounded token/
  delayed-response regression correction. Final clean head
  `47f0cacf3e6d6d84281403c38061265ebaee722b` closes delayed success/error races across all three
  Chrome profiles and passes the full 10 focused, 131 pass/2 intended skip adjacent, adversarial,
  static, mypy, asset, fixture, and diff gate. The same reviewer returned exact-head `PASS` with
  P0=P1=P2=P3=0 after independently repeating the full bounded gate.
- Track C navigation: visible task `019f9c8d-cfa8-76c1-9111-7600e1180d35`, worktree
  `C:/Users/prave/.codex/worktrees/ee40/Renpy`, dispatched concurrently with explicit
  `gpt-5.6-sol` High from exact frozen checkpoint `4827b06`. It owns only deterministic Python
  path/detail/source navigation and focused tests. It completed clean exact head
  `13876361039ab120c7ef4d6765ae74c9f572647d` after a final post-edit provider-free gate of 75
  tests, Ruff, strict mypy, JSON/hash checks, and diff hygiene.
- Track C reviewer: visible read-only task `019f9ca6-cb8b-7503-afc0-9e4c51cd0946`, worktree
  `C:/Users/prave/.codex/worktrees/6915/Renpy`, explicit `gpt-5.6-sol` High, returned `FAIL /
  CHANGES REQUIRED` at exact head `13876361039ab120c7ef4d6765ae74c9f572647d`, updated to P0=0,
  P1=1, P2=3, P3=0 after reproducing backward continuation resolution through control-only
  merge/label topology. The P2s require an echoed selection ID in forged-selection HTTP 404 JSON,
  removal of a type-only runtime import that breaks V2 import isolation, and use of the exact
  centrally frozen six-state fixture filename. The worker corrected the P1 with three end-to-end
  continuation/path/detail topology fixtures. Corrected clean head
  `fb0f2ecd207848248e674f9c76af7a3d505019fb` passes the worker's
  final provider-free gate of 22 focused, 7 targeted, 192 adjacent, Ruff, strict mypy, JSON/blob/
  diff/privacy checks. The same reviewer returned exact-head `PASS` with P0=P1=P2=P3=0 after
  independently passing 22 focused, 7 finding-specific, 192 bounded, three architecture, and 16
  loopback tests plus static gates. A premature partial cherry-pick `c046d8c` was immediately
  reverted by `f325d07`; after both reviews passed, the complete reviewed Track C chain was
  integrated byte-equivalently as `3161261` and `659d612`.
- Additive cross-track freezes are recorded at `4bfcf5e`, `ec8a194`, and `a9ca7e2`: server-owned
  continuation bindings, tree-wide deduplication, and exact path/detail envelopes. These do not
  broaden product scope.
- Track B's complete reviewed chain was integrated byte-equivalently as `472129b`, `a3eb8fa`, and
  `a8e0ddf`. The shared six-state fixture has blob `906fa04e3c3451b6cded1bcb84a70144f16727b9`
  in both reviewed heads and the integration tree.
- Integrated provider-free verification at `f70ca88` passes: 239 Story Map V2 tests (three opt-in
  browser cases separately pass), 317 bounded M10-M13/storage/API/navigation/privacy tests (two
  hardware tests deselected), all three final Story Browser Chrome profiles, M12 real Chrome, 33
  browser-asset/privacy/import tests, Ruff, strict mypy over 108 source files, four JavaScript
  syntax checks, JSON/schema/fixture parsing, manifest integrity, whitespace, and tracked-clean
  containment. The old M13 hardware harness still times out because it waits on a DOM element
  object that CDP serializes as falsey; a diagnostic run proved the exact expected M10 control and
  `record_id` were rendered. The untouched historical harness is excluded, as previously frozen,
  rather than counted as Track B/C product evidence.
- The first private zero-submit preview safely exposed one accepted-core lineage projection gap
  before provider construction: an external non-story ancestor was not part of the transmitted
  story-choice alias set. Existing Track A worker corrected only that projection at `5926a00`; the
  same independent reviewer returned exact-head `PASS`, P0=P1=P2=P3=0. It was integrated
  byte-equivalently as `83d1a4f`; 241 V2 tests plus Ruff, strict mypy, and whitespace pass. No
  provider construction, attempt, or call occurred during the failed preview or correction loop.
- The successful zero-submit preview bound request `d4d44735...`, confirmation `cd367171...`,
  approved schema `4febec35...`, 9,322 payload bytes, exact 12/4/8 counts, Terra/High/fast-off, and
  an absolute one-call ceiling. Its identical rebuild was executed once. Exactly one provider
  construction, submit attempt, and call occurred; identity could not be verified, so execution
  failed closed and the ledger entered terminal `completed_no_retry`. No retry, substitute,
  auditor, mapper rerun, or second provider action occurred.
- Subsequent generalized corrections all passed same-reviewer exact-head rereview with
  P0=P1=P2=P3=0 before byte-equivalent integration: presentation lineage `75b1484` -> `b61ab8e`,
  role-qualified public selection IDs `497ccf76...` -> `5565244`, typed target-entry failure
  `ba953754...` -> `253fba0`/`5760eb3`, and path-panel wrapping `834246b3...` -> `cff2388`.
  Rejected predecessor `53c1494` remained out because its broad `ValueError` catch could mask
  stale authority.
- Initial final cross-track review used visible read-only task
  `019f9d58-0eec-77f0-9049-61f8d5ba6e81`, worktree
  `C:/Users/prave/.codex/worktrees/4397/Renpy`, explicit `gpt-5.6-sol` High, with task fast mode
  unavailable/unverified. At exact candidate `60b0441` it returned `FAIL / CHANGES REQUIRED`,
  P0=0/P1=0/P2=2/P3=1: a stale Detail response could overwrite the newer selection, and the
  browser contract rejected a valid identical continuation binding reused in separate root choice
  trees. The P3 concerns compact witness presentation and is nonblocking.
- The existing Track B worker corrected only those two P2s at exact head
  `8e6de6f395494b006d5eec5387c17a3b1c6654a1`. The existing Track B reviewer passed that exact
  head with P0=P1=P2=0/P3=1 after focused, six-profile Chrome, full family, adjacent, adversarial,
  static, asset, fixture, and privacy gates. The correction was fast-forward integrated exactly.
  The same final cross-track reviewer then returned exact-head `PASS` at `8e6de6f` with
  P0=P1=P2=0/P3=1 after 275 Story Map tests, 92 adjacent tests, static gates, 20/20 adversarial
  mutations, artifact-hash verification, and containment review.
- Prior reviewed product head is `8e6de6f395494b006d5eec5387c17a3b1c6654a1`. Outside-Git private
  acceptance report SHA `a42202b7...` passes with 12 events, four choices, eight arms, four known
  rejoins, all 24 Detail/source targets available, 23 paths available and one honestly unresolved,
  all five target classes proven, zero-call reopen, unchanged protected inputs, and unchanged
  terminal ledger. Working project SHA is `0bd02eb8...`.
- Outside-Git real-Chrome report SHA `df3c721f...` passes at 100%/200% with zero overflow,
  clipping, overlap, mojibake, remote requests, browser errors, or new provider activity; focus and
  selection return pass. A fresh recapture at exact reviewed product head `8e6de6f` reproduced the
  report and all four previously presented overview/deep-path PNGs byte-for-byte, with unchanged
  protected inputs and terminal one-call ledger.
- The user did not approve the prior screenshots. Their comparison with the accepted Phase 01
  direction instead approved one bounded browser refinement: compact nonduplicated fallback hero,
  numbered presentation of existing accepted events without new semantic grouping, restrained
  accents, desktop two-column/narrow stacked arms, mechanics-first witness with full raw scenes in
  Analysis notes, and compact 200% masthead. No provider/server/API/navigation/private change is
  authorized.
- Same Track B reviewer passed corrected exact head `848dce0c06300fb90722ba00a2d69bcd8268793c`
  with P0=P1=P2=P3=0. The reviewed product/test blobs were integrated byte-equivalently through
  `eecaf590f608d62d74b32c4af2b5a665d681bee5`; integrated provider-free gates pass with 16
  real-Chrome focused tests, 269 Story Map V2 passes, 136 adjacent passes, and clean static gates.
- Same final cross-track reviewer passed exact lifecycle head
  `8d8aecf9c668e85cafd5b50c6fb0c8180771eab1` with P0=P1=P2=P3=0 after 16 focused, 269 Story Map
  V2, 137 adjacent, maximum-bound browser, static, identity, privacy, and containment checks. The
  inherited compact-witness P3 is closed.
- Replacement private browser report SHA `75143227693ed14a8e93ccdd29578c564c12c59156c1f6d79d2dc31e7f53042f`
  passes 100%/200% with zero overflow, clipping, overlap, mojibake, remote requests, or new provider
  activity; focus and selection return pass, protected inputs and ledger are unchanged. The four
  replacement PNGs are captured outside Git; prior candidates are archived under
  `output/m15-story-map-v2-phase-03-20260726-011613/pre-refinement-8e6de6f/`.
- User screenshot approval: complete. The user reviewed the replacement 100%/200% overview and
  deep-path captures and replied “looks better proceed.”
- Final local release validation: pass on approval head `f56f238`; 1,420 deterministic tests passed
  with 16 hardware-sensitive tests deselected, Ruff and strict mypy over 109 source files passed,
  dependencies and four JavaScript files passed, and isolated sdist/wheel build, wheel install,
  isolated import, packaged assets, and whitespace checks passed.
- First pushed-head GitHub result: run
  [`30210504223`](https://github.com/nmpraveen/renpy-story-mapper/actions/runs/30210504223)
  failed only because three historical fake-provider tests used fixed 500 x 10 ms polling while
  the hosted Windows suite was heavily loaded. The other 1,418 tests plus Ruff, strict mypy,
  dependency, JavaScript, whitespace, package build/install/import, and asset gates passed.
  The bounded test-only correction replaces those fixed caps with a 30-second monotonic deadline;
  its three affected regressions pass three consecutive local runs.
- Post-correction local Release: pass; 1,420 deterministic tests passed with 16 hardware-sensitive
  tests deselected, plus Ruff, strict mypy over 109 source files, dependencies, four JavaScript
  files, whitespace, isolated sdist/wheel build, wheel install, isolated import, and packaged assets.
- Post-correction independent review: exact head `3cde906febba265ab8b4d13798bf4444e6d704ba`
  passed with P0=P1=P2=P3=0; the reviewer confirmed the diff is test/lifecycle-only and reran the
  three affected tests, workflow contracts, Ruff, and diff checks.
- Replacement pushed-head GitHub check: run
  [`30212233098`](https://github.com/nmpraveen/renpy-story-mapper/actions/runs/30212233098)
  passed at exact reviewed head `3cde906`; PR #28 was `CLEAN`, open, non-draft, and unmerged.
- Final lifecycle-only PR head: `1dd55ff61f20bbc75618a1cab613ac5e7c52b1ec`. GitHub run
  [`30213028297`](https://github.com/nmpraveen/renpy-story-mapper/actions/runs/30213028297)
  passed at that exact head. The native goal then closed at PR readiness with PR #28 still open
  and unmerged, satisfying the approved Phase 03 contract.
- Post-goal merge: the user separately approved a normal merge. PR #28 merged on 2026-07-26 at
  `27035cba5c55585ea5dbeb48e6dd1cd026c44941`; its merge tree exactly matches reviewed head
  `1dd55ff`. Local `main` and `origin/main` both resolve to `27035cb`; preserved untracked
  user/private paths remain untouched.
- Current action: the Phase Coordinator creates and records the exact Phase 04 native goal, then
  advances to `In progress` before product-code changes and dispatches Track A/Track B from the
  reviewed contract checkpoint. Provider work, private acceptance, Phase 05, M14, and historical
  Stage H/E work remain unauthorized at `Ready`.

## M13 historical lifecycle

The user authorized one bounded provider-free post-merge M13 correction on 2026-07-17. The exact
merged baseline and `origin/main` match, and the merge commit tree exactly matches PR #23's
reviewed second-parent tree. Static inspection confirms that cross-phase reopen can undercount
disjoint prior cumulative and current durable usage through component-wise maximums. M13 is
therefore reopened to Verification on `codex/m13-post-merge-usage-recovery`; M14 remains deferred.
The Phase Coordinator owns the single native goal. Visible Track A
`019f730d-53a7-7d51-a6b5-b5a4062c79d3` and Track B
`019f730d-53a7-7d51-a6b5-b5c28fef11f4` were created in separate worktrees after contract commit
`6f9fb52b30a2de92642450d9de67c2552c94417f`; Track C was deferred until the integrated product
candidate froze, then created in its own read-only worktree.
Visible task dispatch can select `gpt-5.6-sol` and High reasoning but exposes no fast-mode
selector, so fast-mode state is unavailable and unverified rather than claimed disabled.

Track A produced failing-first commit `249132d`, main provenance correction `b9b8f63`, loop-one
correction `0cb4b3d`, and loop-two correction `82d2331`. Its final focused gate passed 90
provider-free scheduler/workflow/pipeline/API tests plus Ruff, strict mypy, and diff checks.
Reviewer A returned `FAIL` at exact clean head `82d2331` with one remaining P1: an opaque legacy
browser ambiguity can be preserved by a cache-only phase but become unreachable when a later
phase uses a different scheduler compatibility ID, after which a provider-free adversarial probe
observed nine prohibited submits. Both authorized correction/rereview loops are consumed. The
Phase Coordinator stopped without integrating Track A, running Release, creating Track C,
pushing, opening a corrective PR, transmitting to a provider, merging, or starting M14. Renewed
user authorization is required for any third narrowly bounded correction and rereview.

Track B independently confirmed the same P1 without edits. Read-only remote audit verified M09
PR #16 is `MERGED` with `mergedAt=2026-07-13T18:55:27Z`, directly contradicting the current
`MASTER_PLAN.md` and M09 completion-report claims that it remains unmerged; the authorized Phase 3
reconciliation has not begun. The failed Track A range changes scheduler, workflow, pipeline, and
browser API accounting. Historical M10-M12 authority/source hashes and unchanged static browser
assets remain inheritable facts, but prior live/replay/private-scale accounting and browser retry
lifecycle runs are not exact-head proof for any future corrected candidate. M14 remains deferred.

The user then resumed the native goal and authorized all bounded provider-free correction and
rereview loops reasonably necessary for this exact cumulative-resource accounting defect,
including integration, focused tests, one Windows Release, Track C, lifecycle/evidence
reconciliation, push, corrective PR creation, and CI. Verification resumes through the existing
visible Track A and Track B tasks. Live-provider transmission, PR merge, M14, destructive cleanup,
broad unrelated refactoring, and materially broader product scope remain excluded.

## Post-merge cumulative-resource correction (complete)

The corrected product head is `a71d5888d55d0d5a19ddb84efd522dccdcbe282d`, descended from
merged PR #23 baseline `d37fe236d576eea553fb7aef9ecc2c5b6c2e0c5a`. Track A visible task
`019f730d-53a7-7d51-a6b5-b5a4062c79d3`, Track B visible task
`019f730d-53a7-7d51-a6b5-b5c28fef11f4`, and Track C visible task
`019f7376-756d-75c1-af72-d572b5bf36ba` all used `gpt-5.6-sol` with High reasoning. Their task
surface exposed no fast-mode selector, so fast mode is unavailable/unverified rather than claimed
disabled.

The correction separates exact prior cumulative usage, checkpoint current-phase usage, and durable
events. Disjoint calls/input/output/elapsed/known cost add once; peak concurrency is a maximum;
estimated usage is monotonic; unknown contributing cost remains unknown. Exact checkpoint coverage
binds event identity/state/payload hash, excludes covered events from re-addition, and adds later
uncovered events once. Supplied prior usage cannot regress exact checkpoint prior. Run-scoped opaque
legacy usage survives scheduler/pipeline/API/browser writers; cache-only replay remains zero-submit,
while any ambiguous miss fails closed.

Track C initially returned `CHANGES REQUESTED` at `5c792c1` because a checkpoint's stored phase
aggregate could be lowered independently from five exact covered transmitted events. Failing-first
commit `bd46caf` reproduced one escaped submit; correction `a71d588` derives covered usage from the
exact events and rejects conflicting calls/tokens/peak/estimated/cost or regressed elapsed before
cache, admission, or submit. Track A Reviewer A, Track B, and final Reviewer C all return `PASS`
with no P0-P3 at `a71d588`.

Parent verification passes 97 scheduler/workflow/pipeline/API tests, Ruff, strict mypy over the four
changed production files, and the full-range diff check. The single authorized local Windows
Release passed at predecessor candidate `5c792c1`: 1,149 passed, 7 hardware-sensitive deselected,
plus every quality/build/package gate. It was not repeated after the final two-file correction; the
exact corrected head instead has focused tests, two independent rereviews, and exact pushed-head
GitHub Release run `29632020095` passed. Exact final PR head
`9e7d387025ed29fdd1c7a43442db4dffda3db0ad` then passed Release CI run `29632577820` and merged
as `3fff4762ce3e46174723e2adf35c2f7db19f2b2e`. Historical browser UI/static navigation facts remain
inheritable because those assets did not
change. Prior live-provider, browser retry/reopen accounting, private-scale accounting, and replay
counts remain historical exact-head evidence rather than proof of the correction. No live provider
transmission, M14 work, destructive cleanup, or protected-path change occurred during the corrective
cycle or merge closeout.

The user approved and activated M13 on 2026-07-16 with binding amendments for bounded internal
summary segments, logical-job/transport-batch separation, a lazy claim DAG, context-aware
contradictions, claim-level salvage, one required cloud adapter, simple manifest consent,
route-aware hierarchy, release-priority order, full provider-free private-scale simulation,
bounded live acceptance, and privacy-safe storage. The single early semantic gate passed; work is
proceeding in the contract's release-critical order.

The 2026-07-17 final bounded correction authorization preserves the existing done condition and
semantic `PASS`. Phase 0 fetched and verified local, remote, and PR head
`e17ba5e3de295c83bba223f858098b65d84291b6` against merged baseline
`f67df8a7cb805bf4adf8590585bae700d2f3117f`; PR #23 is open, non-draft, mergeable, and clean. The
tracked worktree and index were clean. Existing untracked `docs/handoffs/`, `output/`, and `tmp/`
content was preserved untouched.

## Historical final bounded PR #23 correction cycle

The parent coordinator's read-only Phase 0 audit reproduced findings 1-5, 7, and 8 by deterministic
probe or exact code path at `e17ba5e`; finding 6 is the current false-positive candidate. Exact
evidence includes: phase-local `record.usage` propagation in `pipeline.py`; subtype history checked
only after admission; no durable pre-submit reservation consumed by resume accounting; browser
retry identity persisted only after pipeline return; transmission inferred from exception class;
the privacy probe accepting `secret_key`, `secretValue`, `token_value`, and normalized variants;
and `app.js` selecting `response.citations[0]`. The focused alternative-route projection test
passes and preserves a route-B artifact without route-A status or badge, but Track B and its
independent reviewer must prove the full validation/publication/hierarchy/rendering path before
the finding is closed as a false positive.

No product edit, provider call, PR mutation, merge, or protected-untracked-path change occurred in
Phase 0. The system `py -3.12` interpreter is not installed against this checkout and no repository
`.venv` exists; provider-free probes therefore inserted `src` in-process without changing the
environment. Collaboration dispatch exposes model and reasoning selectors, but no fast-mode
selector. Child tasks will explicitly use `gpt-5.6-sol` and High reasoning; fast-mode state will
be recorded as unavailable and unverified.

Track A froze the cumulative-usage, transmission-attestation, reservation, and browser retry
identity interfaces before worker divergence. Its final independently rereviewed head
`2685de031db68682697134e5cad64e0246e1929d` passes with no P0, P1, or P2 after one bounded
reviewer-driven correction. Track B independently passes at
`251e063fc0467f73f14d0771b2a4fd236772e6b0` with no P0, P1, or P2 and confirms finding 6 is a
false positive across validation, publication, hierarchy, rendering, and unchanged M12 bytes.

The parent integrated Track A first, rebased Track B's three semantic commits onto that exact
head, and fast-forwarded the result without conflict. Integrated candidate head is
`9ab1dbd873420ad4a7f679b87bd39b1ee9b8582b`; the lifecycle is now `Verification`. No provider
call, push, PR mutation, merge, protected-untracked-path change, or M14 work occurred during track
execution or integration.

Focused verification at lifecycle head `532eefc933460ed1876a715df1b12a921e24b3c0` passed 227
tests, Ruff, strict mypy over 92 source files, JavaScript syntax, and both correction-range diff
checks. Final independent reviewer `/root/m13_final_integrated_review` nevertheless returned
`FAIL` with one P1 and no P0/new P2. An unresolved durable reservation for logical attempt 1 is
charged conservatively to cumulative usage but is not reconstructed into per-job attempt history;
after reopen, `maximum_attempts_per_job=1` therefore admitted another submission as attempt 1. A
provider-free CPython 3.12 probe observed calls increase from 1 to 5. Findings 1 and 3-8 pass, and
finding 6 is confirmed a false positive.

Track A already consumed the one bounded reviewer-driven correction and rereview permitted by the
user's final handoff. The coordinator therefore stopped without a second product correction loop,
Release/browser/private-scale/GitHub acceptance, push, PR mutation, merge, provider call, or M14
work. M13 remains in `Verification`; PR #23 is not currently ready, the native goal remains active,
and another narrowly bounded correction requires explicit user authorization.

The user supplied that explicit authorization in the 2026-07-17 resume handoff: exactly one
additional narrowly bounded failing-first correction for recovered reservation attempt history,
one independent rereview, and only the remaining contract-required verification/evidence needed
to make existing PR #23 genuinely ready. The lifecycle resumes at `Verification`; no provider/live
transmission, merge, M14 work, or protected untracked content is authorized. The current thread was
dispatched with `gpt-5.6-sol` and High reasoning. Its thread API exposes no fast-mode selector, so
fast-mode state remains unavailable and unverified rather than claimed disabled.

The additional correction is frozen at `a7e242b4534f7217d469308392d932795201cb57`.
Its failing-first reopen regression failed before product edits, then the workflow/scheduler gate
passed 54 tests plus Ruff, strict mypy, and diff checks. Independent reviewer
`/root/m13_reservation_rereview` nevertheless returned `FAIL` with one P1 and no P0/new P2:
multiple compatible durable reservations for the same historically reused logical attempt are
collapsed to one recovered history slot, so a ceiling of two can still admit a third submission.
The reviewer reproduced this provider-free. The additional correction/rereview authorization is
consumed. The in-progress Release run was stopped after the blocking verdict; no provider/live,
browser/private-scale, GitHub, push, PR mutation, merge, protected-untracked-path change, or M14
action occurred. M13 and the native goal remain active in `Verification`; PR #23 is not ready.

The user then explicitly authorized one further narrowly bounded correction and independent
rereview for exactly this duplicate-reservation multiplicity P1. Verification resumes without
changing the done condition or semantic `PASS`. Provider/live transmission, merge, M14, protected
untracked content, and any broader product work remain excluded.

The duplicate-reservation correction is frozen through `18f2edf` and reviewer-driven exact
nontransmission correspondence correction `ba71cda82eba2e605f97041923329ee9afd2a681`. Failing-first
regressions proved both multiplicity cases and the finalized `NOT_TRANSMITTED` zero-call case before
the fixes. The reservation-focused set passes 5, workflow/scheduler passes 57, and Ruff, strict
mypy, and diff checks pass. Independent reviewer `/root/m13_multiplicity_rereview` returned `PASS`
at exact clean head `ba71cda` with no P0, P1, or new P2. M13 remains in `Verification` only for the
minimum final Windows/PR evidence required at the corrected head; no provider/live rerun is
authorized or needed for this provider-free correction.

Final Windows Release validation passed at the reviewed correction/evidence head: 1,135 tests
passed with 7 hardware-sensitive deselections in 683.13 seconds; Ruff, strict mypy over 92 source
files, dependency, JavaScript, whitespace, isolated build/install/import, browser-asset, and notice
checks all passed. Historical current private-scale and live/replay evidence remains exact-head
evidence; the narrow provider-free recovery correction is covered by its failing-first fault cases,
independent review, and full Release. Product/evidence head `120a4ec` was pushed to existing PR #23
and remotely verified open, non-draft, mergeable, and `CLEAN`; GitHub reports no configured status
checks. At that historical checkpoint M13 was `PR ready`; PR #23 later merged. No provider/live
rerun, M14 work, or protected-untracked-path change occurred during that correction.

## Historical prior correction verification (not current-cycle proof)

The bounded correction runtime is frozen at
`3533d49a61e77c76794b4ba8338ccf60ee8201ef`. Worker corrections were integrated sequentially as
`01581ad` (browser provider settings), `7c784d4` (shared privacy validation), `9a93edf` (exact M12
authority), and `a5d9f9e` (compatible durable resume and conservative failed-call accounting).
Coordinator commit `3533d49` completes exact existing-workspace citation navigation, durable
browser reopen, acceptance coverage, and packaged asset reconciliation. The machine-readable
current evidence index is `docs/milestones/M13/CURRENT_EVIDENCE.json`.

Current gates pass: the focused M13 suite is 291 passed/1 expected browser-wrapper skip; adjacent
M12 plus M13 persistence is 139/1; Windows Release is 1,079 passed/7 hardware deselected with
Ruff, strict mypy over 92 source files, dependency, JavaScript, whitespace, isolated build/install/
import, browser-asset, and notice checks green. Fresh real Chrome passes at 100% and 200% with
zero remote requests and exact M10/M11/M12/M13 Detail/Evidence navigation. Fresh provider-free
private-scale acceptance passes 1,812 scenes, 2,590 logical jobs, full fault/recovery hierarchy,
source/authority immutability, and exact zero-call replay with all safety counters zero.

Lifecycle was `PR ready` at that historical head. Independent reviewer `/root/m13_final_targeted_review` passed exact integrated head
`e79384bb7d16b93b734a47111981996261047965` with no P0, P1, or new P2 after 105 + 32 + 2 focused
tests and a clean zero-edit detached review. The approved production-path run at exact head
`677d88152e100afd154bb54da249582ff0a2ffcd` completed with contract-valid terminal `partial`:
90 publishable jobs (88 succeeded, 2 partial), 24 calls, 1,524,766 input and 93,316 output tokens,
the complete route-aware hierarchy, 1,035 published claims, zero unresolved references/cycles,
unchanged source/authority, and no raw prompt/response retention. Exact fail-closed replay made
zero submit attempts/calls/tokens and reproduced artifact hashes and rendering exactly. Sanitized
report SHA-256 is `f97bbfec2f6f1859182c9418dfd92807b006217b6e9498fc5365de96fac0313f`.

The first remote PR check at evidence head `d5fdcaa` was not a product-test failure: its pytest
process was cut off by the repository helper's fixed 900-second limit after reaching 73%, with no
failed test reported; every later Ruff, strict-mypy, dependency, JavaScript, whitespace, build,
install, import, asset, and notice check passed. The complete required local Windows Release had
already passed 1,079 tests with 7 hardware-sensitive deselections. The user then clarified that
local validation must not be rerun but GitHub may run without limits. The workflow and validation
runner therefore remove their repository-imposed job/process cutoffs. Unbounded GitHub run
`29604661539` passed at branch head `7bf54042639a781313cf6c924e09a0ee023a86f2`: 1,081 tests
passed, 7 were deselected, Ruff passed, strict mypy passed over 92 source files, and all dependency,
JavaScript, whitespace, build, install, import, asset, and notice checks passed. The Release step
completed in 806 seconds and the job in 14 minutes 22 seconds without a repository timeout.

## Historical M13 evidence

The prior frozen runtime correction head is `e0fd3bf3dba34a2d936028f3df8773e69d9fc1c8`.
Final-head focused tests passed 70 tests, and Release passed 966 tests with 7 hardware-sensitive
tests deselected plus Ruff, strict mypy, dependency, JavaScript, whitespace, isolated package
build/install/import, asset, and notice checks. Provider-free acceptance passed all 1,812 private
scenes, and real Chrome acceptance passed at 100%/200% with zero remote requests and zero-call
simulator replay.

The one independently configured corrective rereview used `gpt-5.6-sol`, High reasoning, fast
mode disabled, ephemeral/read-only execution, and range `04082c0..9889035`; it returned `FAIL`
with two P1 findings. The single permitted corrective cycle produced `e0fd3bf` and focused/Release/
private/browser checks pass, but no second independent verdict was authorized. The fresh live
manifest was explicitly approved, including external transmission risk. Its one execution failed:
74 jobs, 222 transient-failure attempts, 24 provider calls, zero recorded tokens, no artifacts,
and no replay. It also demonstrated that the previewed consent ID `m13_consent_3bb95e...` changed
to unpreviewed granted ID `m13_consent_d2b91d...` in persisted provider requests. Per the bounded
severity policy, no retry or second correction loop was started. After the same terminal condition
persisted for three consecutive goal turns, the native goal was marked blocked. The native
infographic is complete, and no pull request has been created.

The user subsequently approved a narrowly scoped recovery and resumed the same coordinator task.
Recovery integration started from evidence-only head
`4e2bf7a452b5f6c62f73ab1115a48b75bfd3ad82`, with `e0fd3bf` retained as historical runtime
evidence. Task A `019f6d5a-b372-71d2-a5a4-956e4654d8bc` delivered `902d400` and integrated as
`cb17b55`; Task B `019f6d5a-b33b-7aa0-b64b-56bd73ce580c` delivered `052b850` and integrated as
`edf80ed`. Both exact-base handoffs and clean owned diffs were verified. The new runtime freeze is
`edf80ed233799d2b61fec17a775187711a899cad`; its combined focused gate passed 155 tests plus
targeted Ruff and strict mypy. The one full Release run passed 1,005 runtime tests, Ruff, strict
mypy, dependency, JavaScript, whitespace, and isolated package checks, but one lifecycle-document
test rejected the non-canonical `Status: Integration; ...` line in this file. This evidence-only
normalization closes that exact failure without changing the runtime freeze or repeating Release.
No story-provider call, external code review, or pull request is authorized without its separate
exact approval gate.

Fresh local acceptance at runtime freeze `edf80ed` is complete. Provider-free private acceptance
passed 1,812 scenes with zero remote/provider/process execution and zero-call replay; report
SHA-256 `82663e94c4763c0de14c86e45427b1469ffc29ae98486d2d6cee86b40fee1f4e`.
Worker `019f6d76-c028-7e71-b98a-0f8068fa56b4` passed one real Chrome harness invocation at
100%/200% with report SHA-256 `8d065d7a34521dc834e115d053e2a6a2ab72910532e7bd7d662ef93031f81b02`
and generated the exact zero-submit live preview with SHA-256
`abf81bc760b751d845c198a19b37e1ad2544a7f8df8a9dc00203584105ebd034`.
The local public-synthetic canary preview made zero calls and has SHA-256
`64317773cbfb1ab524be41b8115e6bf7e3e59219e5960443f61de2c9a922a678`.
The user then approved exactly one execution of that manifest. The public-synthetic-only call ran
once without retry and failed after 13.139 seconds with exit 1 because the provider response did
not report its resolved model identity. Provider usage and token counts were unavailable. The
runtime freeze remained unchanged at that checkpoint; live story transmission, external review,
and PR creation were not attempted.

The user then approved the narrow resolved-model correction and use of all Codex sessions in this
thread. Runtime commit `5be797cc57522bc9473cd959fd9744d8426b0f81` records the validated explicit
`--model` selection when Codex CLI 0.144 omits redundant model metadata, still rejects malformed,
conflicting, or different reported identities, and versions that behavior as adapter v3. The
focused matrix passed 59 tests plus Ruff, strict mypy, and whitespace; two independent read-only
audits found no P0/P1 blocker. One fresh public-synthetic v3 canary then passed on its only call in
6.256 seconds with no retry or private content. Final-head Release passed 1,012 tests with 7
hardware-sensitive tests deselected and every build/quality/package gate green. A new zero-submit
live preview at `5be797c` binds exact consent `m13_consent_9e3a24626be81561498eddcec29afa66e9793ef6c879d5425889276a6cc750aa`,
adapter/schema v3, Sol/High/no-fast, 87 logical jobs, and 63 estimated calls. Live story
transmission remains unexecuted pending exact confirmation of that manifest; final full-head
independent review and PR creation remain outstanding.

The user exactly confirmed that preparation and consent manifest. The single live command ran
once at `5be797c` and was not retried. Consent identity remained stable and provider identity was
OpenAI/Codex CLI adapter v3 with requested/resolved `gpt-5.6-sol`, High reasoning, and fast mode
off. After three provider calls it reached terminal `hard_limit`: 395,221 input tokens, 11,142
output tokens, 406,363 total tokens, and 218.358 seconds. It published all 27 scene artifacts, then
stopped 23 summary-segment jobs before attempt; no segment or higher artifact and no zero-call
replay was produced. The persisted subtype is only `hard_limit`; scheduler rules and remaining
budget support `input_token_limit` as an inference because only 4,779 of the 400,000 input-token
allowance remained while call, output, total, and elapsed limits were not exhausted. The synthetic
source hash remained unchanged and all persisted M13 records retain consistent M10/M11/M12/source
bindings. M13 remains verification-blocked; no further live run, final external review, or PR was
attempted.

The user then approved implementing the unrestricted-in-practice rerun plan while retaining the
contract's finite consent and safety boundaries. Runtime commit
`740e3214e84e256f4dab459d3528ddec803e456b` corrects the complete-workload estimate with
serialized request allowances, a calibrated 25,000 input-token runtime allowance per estimated
call, and a live-specific 2x headroom policy. The new provider-free fixture estimate is 87 jobs,
65 calls, 2,463,527 input tokens, and 81,600 output tokens; finite live limits are 130 calls,
4,927,054 input, 163,200 output, 5,090,254 total tokens, 7,200 seconds, and concurrency one.
Retries are disabled for this acceptance so the call ceiling is honest. Release passed 1,015
tests with 7 hardware-sensitive tests deselected and all quality/build/package gates green. An
independent Sol/High read-only review passed with no P0/P1 after 126 review tests and 14 changed-
module tests. Stable zero-submit preview SHA-256 is
`a2fbe4acae8be57e11ef9560a72dc9aa3431df5d95a177f319ecd1ad9063e996`, with preparation
`m13_preparation_564d42c66a9068ffe4878f1c3d9db59749627220213eca3c17a6d97808342ad4`
and consent `m13_consent_1de082368bb65c9a835c65364abeb3a78ff6e29316d4509419a6110d015c06de`.
No provider submit occurred. Provider-free private acceptance then passed all 1,812 scenes, the
complete hierarchy, fault/recovery matrix, and exact zero-call replay with zero network/provider/
game execution; report SHA-256 is
`13226a0d25cff4a63d33f8bdd9d8e1a13f19d2f36a51c0c9e1003cd6a832b0dc`. All three private
inputs and adjacent files remained unchanged. The simulation took about 16m35s and peaked near
6.2 GB, which is accepted verification evidence and a future harness-optimization target. The
exact live manifest had not yet been executed at that checkpoint.

The user then exactly approved preparation
`m13_preparation_564d42c66a9068ffe4878f1c3d9db59749627220213eca3c17a6d97808342ad4`
and consent
`m13_consent_1de082368bb65c9a835c65364abeb3a78ff6e29316d4509419a6110d015c06de`.
The one exact live provider execution made 13 calls, used 616,819 input and 42,505 output tokens,
and completed the route-aware hierarchy with 81 succeeded jobs and 2 valid partial-salvage scene
jobs. A fail-closed sentinel replay then made zero submit attempts/calls/tokens and reproduced all
83 cached jobs, artifact hashes, and deterministic rendering exactly. Source and M10/M11/M12
authority bytes remained unchanged; raw debug retention stayed off. Independent criterion-20
audit found no remaining P0/P1. The harness had incorrectly rejected allowed aggregate `partial`
before built-in replay; commit `0aa0415` accepts only succeeded/partial publication and retains
strict rejection for failed/refused/cancelled/hard-limit outcomes. Combined report SHA-256 is
`93a22d669d625b8366f47792d13a7dac98db1c8bab1f7f85bd0a77b46d81a621`. No second provider
execution occurred. At that checkpoint no PR had been created; the user later explicitly approved
and opened draft PR #23. It later merged at `d37fe236d576eea553fb7aef9ecc2c5b6c2e0c5a`.

M12 is complete and merged through [PR #22](https://github.com/nmpraveen/renpy-story-mapper/pull/22)
with normal merge commit `f67df8a7cb805bf4adf8590585bae700d2f3117f` on 2026-07-16. Its
implementation branch was deleted locally and remotely. No further M12 implementation or review
work is authorized unless a critical regression is demonstrated.

## State rules

1. Keep at most one active milestone contract and, after the user explicitly starts it, one matching native goal.
2. Use these transitions: `Draft -> Semantic review -> Ready -> In progress -> Integration -> Verification -> PR ready -> Complete`.
3. Use `Revise` when semantic review fails; return to `Semantic review` after correction. Use `Blocked` only with a recorded blocker and resume at the interrupted stage.
4. Require a recorded semantic-review `PASS` before broad implementation.
5. Keep the native goal active until the integrated change meets acceptance, required evidence and review are complete, and any contractually required merge gate is confirmed.
6. Update this pointer in the same integration that changes milestone status. Do not infer state from branch names or conversations.

## Authority order

1. User's explicit milestone approval and constraints.
2. `docs/MASTER_PLAN.md` for permanent product scope and exclusions.
3. Active milestone `GOAL.md` for the bounded contract.
4. Active milestone `SEMANTIC_REVIEW.md`, `TASKS.md`, and `COMPLETION_REPORT.md` for decision, execution, and evidence state.
5. This file for the current pointer and lifecycle state.

If these disagree, stop broad implementation, set the semantic decision to `REVISE`, and reconcile the higher authority without inventing scope.
