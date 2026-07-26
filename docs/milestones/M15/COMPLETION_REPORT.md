# M15.1 Story Map V2 Phase 03 report

Status: In progress

Integration baseline: `e81523fe2cc42f1bc3d8dcb1a839bfd28876dfe9`

Integration branch: `codex/m15-phase03-story-browser`

Integration commit: Pending

Pull request: Not created

## Outcome

Phase 03 is approved, preflight is complete, the shared design is frozen, and the single early
semantic review passed before product edits. Visible Track A task
`019f9c58-e638-71a0-b6a2-cb88b72f3d24` is implementing the shared synthesis/storage/projection/API
seams from exact checkpoint `4f6e3a6` in `C:/Users/prave/.codex/worktrees/e7ca/Renpy`.

Track A produced initial clean head `420dbb7`, with 15 focused tests, 186 V2/storage tests, 71
web/M10-M12 regressions, Ruff, strict mypy, schema parsing, and whitespace green. Independent
visible reviewer `019f9c67-af1c-7812-a471-1f6a98572f1c` nevertheless returned `FAIL / CHANGES
REQUIRED` at that exact head: P0=0, P1=2, P2=0, P3=1. Sterile adversarial probes proved that a
stale optional synthesis removes the valid deterministic fallback and that forged successful
provider provenance can be saved/reopened/rendered. The reviewer also found a tautological reopen
 test. Coordinator inspection additionally required removing the known provider-incompatible
 `uniqueItems` schema keyword and adding the real sterile Terra CLI adapter needed for the
 authorized one-call acceptance.

The bounded correction produced `62a0234`: both P1s and the P3 closed, durable provenance became
exact, incompatible schema keywords were removed, and a hardened sterile production Terra adapter
was added under the repository's validated CLI 0.144 identity policy. Rereview found one P2: a
configurable schema path could differ from the preview-validated schema. Final worker head
`2319092` removes that override and passes the exact canonical approved schema bytes through the
one-use isolated process directory. The same reviewer returned final `PASS` with P0=P1=P2=P3=0.
The coordinator integrated the three reviewed commits byte-equivalently as `e4b497f`, `1dcc63e`,
and `50bdc08`; integrated CPython 3.12 focused verification passes 50 tests.

The shared seam was then frozen at integration checkpoint `4827b06`. Track B visible task
`019f9c8d-cfb6-7b32-8c7f-51482bbe39c6` in
`C:/Users/prave/.codex/worktrees/9ea6/Renpy` and Track C visible task
`019f9c8d-cfa8-76c1-9111-7600e1180d35` in
`C:/Users/prave/.codex/worktrees/ee40/Renpy` were dispatched concurrently from that exact commit
with explicit `gpt-5.6-sol` High settings. Their static-browser and Python-navigation ownership is
non-overlapping. Neither has provider or private-artifact authority.

Track C then froze clean exact head `13876361039ab120c7ef4d6765ae74c9f572647d` after its final
post-edit gate passed 75 tests, Ruff, strict mypy, both serialized contract fixtures/hash checks,
and diff hygiene. Independent visible reviewer `019f9ca6-cb8b-7503-afc0-9e4c51cd0946` in
`C:/Users/prave/.codex/worktrees/6915/Renpy` reviewed that exact head; no Track C commit was
integrated yet. Track B remains in progress.

Track C independent review at exact head `1387636` returned `FAIL / CHANGES REQUIRED`, updated to
P0=0, P1=1, P2=3, P3=0 after reproducing a backward continuation through control-only merge/label
topology. Focused tests passed 16; the adjacent matrix passed 172 and failed the
unchanged transitive import-isolation test once. The remaining P2s are missing selection-ID echo in
forged-selection HTTP 404 JSON and a non-authoritative six-state fixture filename. A bounded new
a bounded correction and same-reviewer rereview followed; the rejected head remained unintegrated.

The consolidated Track C correction is clean at exact head
`fb0f2ecd207848248e674f9c76af7a3d505019fb`. Its final provider-free worker gate passed 22 focused,
7 targeted HTTP/import/topology tests, 192 adjacent tests, Ruff, strict mypy, both JSON/blob checks,
and diff/privacy hygiene. The same reviewer rereviewed the exact corrected head; it remains
unintegrated.

The rereview returned `PASS` at exact Track C head `fb0f2ec`, P0=P1=P2=P3=0. Independent results
were 22 focused, 7 finding-specific, 192 bounded, three supplemental architecture, and 16 loopback
tests plus Ruff, strict mypy, fixtures, and diff hygiene. Track C is integration-ready but is held
until Track B passes. A partial first-commit cherry-pick (`c046d8c`) was immediately reverted by
`f325d07` when that sequencing checkpoint arrived; there is no net Track C product change in the
integration tree.

Track B then froze clean exact head `2069eab3a1f0a018724106f94634e1292072e358` after the final
bytes passed its focused/static/schema/lint gate, real Chrome at desktop 100%, effective 200%, and
390px narrow, 63 adjacent tests, 107-file mypy, asset integrity, and diff hygiene. Independent
visible reviewer `019f9ca9-ab9e-77c0-a2f1-0426f9472084` in
`C:/Users/prave/.codex/worktrees/4f7b/Renpy` is reviewing that exact head. One accidentally enabled
out-of-scope M13 hardware smoke timed out on a pre-existing evidence selector and is recorded
separately, not counted as Track B evidence. No Track B commit is integrated yet.

Track B independent review at exact head `2069eab` returned `FAIL / CHANGES REQUIRED` with
P0=0, P1=0, P2=5, P3=0. The P2s cover the shared fixture filename, deep/exact map bounds and
non-empty unavailable reason, reversible path-panel context, missing authoritative reachability/
item warnings, and browser-invented witness mechanic placement. A bounded new worker commit, full
three-profile Chrome/131-test adjacent gate, and same-reviewer rereview are in progress.

## Preflight evidence

- `git fetch --prune origin` completed.
- Local `main` and `origin/main` both resolved to
  `e81523fe2cc42f1bc3d8dcb1a839bfd28876dfe9`, the clean Phase 01/02 merge.
- The tracked worktree was clean. Existing untracked `.playwright-cli/`, prior handoffs,
  `output/`, and `tmp/` were preserved.
- `src/renpy_story_mapper/story_map_v2/` and its focused tests exist on `main`.
- Private package:
  `C:/Users/prave/Documents/Codex/Renpy/output/m15-story-map-v2-phase-02-20260724-2135/`.
- `acceptance-summary.json` reports `complete`, 1/1 chunks, 12 events, four story choices, eight
  branch outcomes, zero validation failures, and zero provider calls added by reassembly.
- Protected source, archive, and project-copy records each match their recorded SHA-256, byte
  length, and nanosecond modification time.
- Package SHA-256 values: acceptance summary
  `4eff2c54b1eccd65bdb92c996afc3cc6a755737230b626f1ed7c4a1d5f131d1f`, execution ledger
  `087494e4289e86dd0d49e8ca39c43478c2b0d5cf73613903c467c1a5df943edd`, core JSON
  `8ec7c9f5d2f3e4093029e9ece22777a9191c05a11a93dd8657ea81a42143c8b3`, and core Markdown
  `4d90eec56fd24c99e920d03c523b7dbf3b80f61b652c458ff3e531b20dd60700`.

## Acceptance evidence

| Criterion | Result | Evidence |
|---|---|---|
| 1 | Pass | Exact baseline/fetch/preflight above |
| 2 | In progress | Contract locked; active native goal/task `019f9c53-6ef8-7a00-9ec0-f06c5e9dcdb0`; all three worker tracks are visible, while B/C reviewers remain to be dispatched at their frozen heads |
| 3 | Pass | `SEMANTIC_REVIEW.md` ends `PASS` before product edits |
| 4-18 | Pending | Implementation, integration, private acceptance, review, and PR evidence remain |

## Validation

| Command / review | Result | Artifact or notes |
|---|---|---|
| `git fetch --prune origin` and exact ref comparison | Pass | Local and remote `main` both `e81523f` |
| `git status --porcelain --untracked-files=no` | Pass | Zero tracked changes before lifecycle edits |
| Phase 02 acceptance-summary structural audit | Pass | Complete 1/1; 12/4/8; zero failures |
| Protected fingerprint/size/mtime recomputation | Pass | All three records match |
| Early semantic review | Pass | `docs/milestones/M15/SEMANTIC_REVIEW.md` |
| Native goal creation | Pass | Active goal/task `019f9c53-6ef8-7a00-9ec0-f06c5e9dcdb0` exactly matches the done condition |
| Track A initial worker checks | Pass at rejected head | `420dbb7`: 15 focused, 186 V2/storage, 71 web/M10-M12, Ruff, strict mypy, schema parse, whitespace |
| Track A independent review | Fail | Task `019f9c67-af1c-7812-a471-1f6a98572f1c`: P0=0/P1=2/P2=0/P3=1 at exact head `420dbb7` |
| Track A final independent rereview | Pass | Exact worker head `2319092`: P0=P1=P2=P3=0; 50 focused, 210 V2/import, 82 storage/web/M10-M12, Ruff, strict mypy, schema binding, whitespace |
| Track A integration | Pass | Reviewed commits integrated byte-equivalently through `50bdc08`; coordinator CPython 3.12 focused set 50 passed |
| Track B/C dispatch | In progress | Visible tasks `019f9c8d-cfb6-7b32-8c7f-51482bbe39c6` and `019f9c8d-cfa8-76c1-9111-7600e1180d35`, exact base `4827b06`, explicit `gpt-5.6-sol` High, non-overlapping scopes |
| Track C initial worker gate | Rejected by review | Exact head `1387636`; reviewer P0=0/P1=0/P2=3/P3=0; focused 16 passed, adjacent 172 passed/1 failed; correction/rereview pending |
| Track B initial worker gate | Rejected by review | Exact head `2069eab`; reviewer P0=0/P1=0/P2=5/P3=0; correction/full rerun/rereview pending |

## Review findings

- No unresolved semantic-gate finding.
- Product, integration, private acceptance, responsive browser, and final exact-head review have
  not yet occurred.
- Track A is integration-ready and integrated; Tracks B/C, their reviews, integrated provider-free
  verification, private acceptance, screenshots, final review, and PR evidence remain pending.

## Integration and PR state

- Integrated diff reviewed against contract and exclusions: No
- Required checks passed: No
- Blocking findings resolved or explicitly accepted: No
- User approved final-head screenshots: No
- PR genuinely ready: No

## Remaining limitations

- Track A product code is integrated; Track B/C implementation and their exact-head reviews are
  still in progress.
- No provider preview or synthesis submission has occurred.
- The accepted Phase 02 core remains an outside-Git developer artifact until the coordinator's
  later private acceptance imports a copy into the supported project storage.
- Fast-mode selection is unavailable in the visible task creation API and will be recorded as
  unavailable/unverified for task dispatch. Exact live Terra fast-off identity remains mandatory.

Complete the native Codex goal only when `PR genuinely ready` is `Yes`, final screenshots are
explicitly approved, and every acceptance row has durable evidence.
