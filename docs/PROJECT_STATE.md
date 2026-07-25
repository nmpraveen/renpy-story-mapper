# Ren'Py Story Mapper project state

Updated: 2026-07-24 (Phase 02 blocked after the single authorized live run failed at transport)

`docs/MASTER_PLAN.md` owns product scope. This file owns the operational pointer to one explicit milestone contract. Milestone-local files own acceptance and evidence.

## Current contract

- Status: Blocked.
- Active milestone: M15.1 semantic Story Map correction inside M15.
- Contract: [`docs/milestones/M15/GOAL.md`](milestones/M15/GOAL.md).
- Original M15 baseline: `a447a4eefbd7c093bdb2767e62a393805af068ac`.
- M15.1 correction base: `55ae57406cfb07a3c088d0dfd7c3b7e04ca9a719`, verified equal locally,
  on the integration branch remote, and on open PR #26 at correction preflight.
- Integration branch: `codex/m15-msday1-narrative-map`; existing
  [PR #26](https://github.com/nmpraveen/renpy-story-mapper/pull/26) remains open and unmerged.
- Current Phase 02 verification checkpoint: Track A reviewed exact head `319d13e9` and Track B
  reviewed exact head `ca9cd4a`; both returned `PASS` with no unresolved P0-P2. The integrated
  implementation and generalized private-preflight correction were frozen at `cbbe3ef`; 287
  Story Map V2/relevant M10-M12/workflow tests plus Ruff, strict mypy, import isolation, and
  whitespace pass. Zero-submit confirmation `2d6b67f...72fa98` bound the unchanged private
  identities to two source-ordered chunks (9,376-token maximum), exact Luna/High/fast-off,
  fallback disabled, and four story choices/eight arms. The one authorized execution returned two
  sanitized sterile-CLI transport failures before any hosted submission (`hosted_attempts=0`) and
  preserved a 0/2 partial core. Final reviewer task `019f96fb-96eb-7120-b121-7815a2584a9c`
  returned `CHANGES_REQUIRED` at `1121e15` with P0=0/P1=3/P2=3/P3=0: the core had wrong physical
  rejoins and inherited nested effects, cloud attempt accounting undercounted both invocations,
  failed provenance was dropped, the plan contained a 14-token first packet, the exact-head
  lifecycle test failed, and provider-generated coverage was absent. The one bounded provider-free
  correction `8158764` fixes the first five issues; 290 combined tests and all static gates pass.
  Corrected preview `e50d659a...da5f0` is one coherent 9,390-token call with accepted four-choice/
  eight-arm mechanics, exact Luna/High/fast-off, and fallback disabled. It has not been executed.
  Same-task rereview at exact clean head `da7ecfa` closed all five original provider-free findings
  but returned `CHANGES_REQUIRED` with P0=0/P1=0/P2=1/P3=0: a schema-valid but overlay-invalid
  response still loses execution provenance in the outside-Git runner before partial assembly. The
  first correction/rereview found one remaining provider-free P2. The user explicitly authorized a
  second provider-free correction/rereview and one new live run only after reviewer clearance.
  Correction `4b1b74d` now preserves the untouched completed execution record when deterministic
  overlay rejects a schema-valid mapper response; its provider-free probe passes. The expanded
  relevant suite passes 294 tests plus all static gates: the reviewer's 291-test matrix plus three
  explicitly included `tests/test_m12_architecture.py` checks. Same-task exact-head rereview passed
  `211fd2e` with P0=0/P1=0/P2=0/P3=1 and granted clearance for exactly the one newly authorized
  live run bound to confirmation `e50d659a...da5f0`. The regenerated preview independently matched
  one 9,390-token/755-span packet, exact four-choice/eight-arm mechanics, Luna/High/fast-off,
  fallback disabled, protected fingerprints, and the authorized confirmation. That run was spent
  exactly once and returned one conservatively counted cloud `transport` failure after 1,718 ms:
  no response, resolved model, token usage, validation failure, retry, or fallback. The resulting
  core is honestly partial at 0/1 completed chunks with the exact failed execution provenance,
  correct deterministic mechanics, zero narrative events, and zero branch outcomes. Protected
  source/archive/project fingerprints remain unchanged. Phase 02 is therefore `Blocked` at private
  acceptance; native goal `019f9676-c357-7803-a891-f03782bbb8ee` remains incomplete and PR #26
  remains draft/unmerged and unmodified. No further live attempt is authorized. Resumption requires
  an explicit transport-policy/correction decision and separately previewed authorization.
  Provider-free diagnostics show Codex CLI 0.144.0 logged in, bundled Luna/High support present,
  and the sterile feature/config overrides parse; `codex doctor --json` exceeded the bounded local
  diagnostic timeout. Because the live transport stores only a sanitized failure category, the
  exact startup cause remains unproven.
  The same Final Integration Reviewer audited the post-run package at exact product head `d4be3f9`
  and returned `CHANGES_REQUIRED`, P0=0/P1=1/P2=0/P3=0, solely for absent provider-generated
  coverage. Confirmation, one-attempt accounting, provenance, mechanics, containment, and
  fingerprints passed independently; no new implementation defect was established.
- Earlier Phase 02 implementation state (superseded): Semantic decision `PASS`. The user started the approved Phase 02 coordinator
  handoff. Visible Early Contract Reviewer task `019f967d-8800-79e2-9dea-5f2412f6eecf` reviewed
  exact clean head `df75532` and returned four P1s with no P0/P2. The one permitted bounded
  correction reconciled lifecycle authority and specifies deterministic branch-event lineage,
  self-contained V2 transports with a transitive dependency gate, and deliberate local-only
  execution. The same reviewer rereviewed corrected exact head `4d32f08` and returned `PASS` with
  no unresolved P0-P2. Shared contract/failing-first freeze `e72fe41` defines versioned records,
  schema, Track A/Track B function signatures, and transitive architecture enforcement. Its five
  original contract tests passed; seven Track A and six Track B tests failed only at their explicit
  `NotImplementedError` seams with no collection error. During A1's exact-authority audit, the
  frozen `SourceSpan` seam proved unable to carry non-choice canonical reachability into the
  overlay. A2 independently found that validated mapper branch summaries and scope text had no
  durable core field. Packet review also proved `StoryChunk` retained only mechanics keys while its
  hash referenced a compact digest that could not be transmitted. Coordinator-owned failing-first
  corrections now require Python-owned span reachability/warnings, canonical compact mechanics
  JSON in every chunk, and branch outcomes plus optional scope text in the core with exact
  deterministic anchors. A final provenance audit adds requested/resolved model, reasoning,
  fast-mode, usage, elapsed, response-hash, and sanitized failure fields to the execution record
  retained by each core chunk. Nine shared contract tests plus Ruff, strict mypy, and whitespace
  pass. Track B then identified that the preview bound the local model but not its configurable
  loopback endpoint; the final narrow correction adds that explicit field to the confirmation hash.
  Tracks resume from these corrected seams without guessing authority or discarding required input,
  output, provenance, or destination identity.
  Stage H V12 remains a failed
  historical attempt with `hierarchy_not_representable` after two calls, 484,092 input tokens,
  33,752 output tokens, and 618,327 ms. It produced no hierarchy, logical record, or publication
  and left protected inputs unchanged. Phase 01 and its local-model supplement remain accepted
  evidence for the new direction.
- Phase 02 visible tracks: Track A coordinator `019f968f-e973-7380-9a26-0443389993a9` in
  `C:/Users/prave/.codex/worktrees/981c/Renpy` and Track B coordinator
  `019f968f-e973-7380-9a26-0464d6f7073f` in
  `C:/Users/prave/.codex/worktrees/0ec5/Renpy`, both based on exact shared head `43c6251` with
  explicit Sol/High settings. The task API has no fast-mode selector, so fast mode remains
  unavailable/unverified.
- Phase 02 design: a bounded `src/renpy_story_mapper/story_map_v2/` package using coherent source
  chunks, one compact mapper shape, Python-owned exact mechanics and stable target anchors,
  chronological partial-capable assembly, and an opt-in refusal-only loopback fallback. The
  supported path must not depend on Stage H/E, adjacent-gap voting, atom allocation, hierarchy
  compilation, repair locks, or exact AI replay. See
  [`PHASE_02_DESIGN.md`](milestones/M15/PHASE_02_DESIGN.md).
- Phase 02 preflight: clean integration head
  `f914908621efb6ccf1728e3028c6176f961e5a7e`; local branch 136 commits ahead of remote; PR #26
  open/draft/unmerged at remote head `bc9a38c`; Phase 01 evidence package and recorded
  source/archive fingerprints present.
- Native Codex goal: active goal/task `019f9676-c357-7803-a891-f03782bbb8ee`, whose objective
  exactly matches the Phase 02 done condition. It remains active through implementation,
  integration, verification, private acceptance, final review, and the draft PR checkpoint.
- Revised semantic gate: [`REVISE`](milestones/M15/SEMANTIC_REVIEW.md) records the historical
  Stage H/E supersession; the current Phase 02 semantic decision is the later recorded `PASS`.
- Accepted Phase 01 outcome: the compact vertical whole-Day-1 overview, visible local choices, and
  selectable witness paths are the product direction. The frozen experiment remains exact at 20
  hosted submissions plus the separately authorized four local calls.
- Phase 01 task topology: Calibration Preparation task
  `019f95b2-8214-7592-8c56-c10e28a7de5d`, Blind Matrix Reviewer task
  `019f95ce-57c2-7103-b416-8bb54592b79d`, and Vertical Prototype task
  `019f95e8-24cb-7be0-b19d-70339367330f` are complete. Each used `gpt-5.6-sol` with High reasoning;
  the visible-task API has no fast-mode selector, so that setting is unavailable/unverified. The
  preparation manifest is `78f08dce...fbbd`; the prototype manifest is `786c7bb3...afa8`.
  The experiment closed at exactly 20 submissions with no retry/replacement. Two schema-valid P1
  cells are operationally quarantined for unauthorized read-only local skill access. P2 selected
  Terra synthesis at 98.05 with three valid witnesses, and all P3 outputs were byte-identical
  correct non-corrective passes, so no default auditor is justified. The six-section prototype has
  five selectable witness targets, 24/24 correspondence assertions, four 100%/200% captures,
  clean reflow, and zero remote/provider calls.
- Final Phase 01 Reviewer task `019f95f8-f3f5-7081-a5be-e0aa00aee2ba` completed its first read-only
  pass and returned `CHANGES_REQUIRED` with one P1: the original checker incorrectly treated exact
  non-story setup controls in the full Luna response as invented story menus. Provider-free
  correction v3 accepts only exact controls—including exact arm boundaries—retains the genuine
  large-Luna inverted-range failure, rejects 18 adversarial field/range mutations, adds zero calls,
  and preserves both earlier evidence states. The corrected
  report recommendation is Luna High/fast-off mapping, Terra High/fast-off synthesis, no default
  auditor, a conservative ~2.5k normal Luna target, and ~10.7k validated Luna maximum. A fresh
  acceptance audit does not adopt ~2.5k as a production cutoff: the scopes contain different story
  material, each cell was sampled once, and Luna passed the complete ~10.7k Day 1. Phase 02 instead
  starts at natural ~8k corridors, splits branch-heavy material nearer ~5k, and keeps ~10.7k as the
  current ceiling. Terra's clean ~16k/~24k public-synthetic calls remain transport/exploratory
  evidence, not complex-story validation; exact total dollar preference remains unresolved. The same
  independent Sol/High reviewer recomputed checker v3, all 18 mutations, all 12 path cells, and the
  full evidence/containment package and returned `PASS` with P0/P1/P2 all zero. The user accepted
  the Phase 01 direction; no default auditor remains a provisional simplicity choice because P3
  tested only a clean candidate.
- The user-authorized local LM Studio supplement is complete: exactly four P1 mapper calls ran on
  the already-frozen small/medium/large/full inputs using installed model
  `qwen3.5-35b-a3b-uncensored-hauhaucs-aggressive`. All four succeeded and were schema-valid;
  checker v3 passed medium/large/full and blocked small for four captions with literal surrounding
  quotation marks. Scores were 97.05 blocked, 96.35 eligible, 97.10 eligible, and 95.85 eligible.
  The separate localhost-only ledger records no retry/fallback and unchanged source/archive. The
  original 20-call PASS package remains frozen. Cloud remains primary. Phase 02 may implement an
  opt-in loopback fallback only for an explicit cloud content/safety refusal or a deliberate local
  run; it must not auto-start/load/download LM Studio/model, handle unrelated failures by fallback,
  or let AI own exact mechanics.

- Git/PR checkpoint: the local integration branch is more than 130 commits ahead of PR #26's historical
  remote failing-first head. The unpushed stack includes the rejected Stage H/E implementation, so
  it is intentionally not pushed before a replacement exists. On 2026-07-24 PR #26 was converted
  to draft and retitled `M15.1: Story Map V2 rewrite (in progress)` with an explicit do-not-merge
  status body. Verified remote head remains `bc9a38c`; the historical failed check was not rerun.
  The PR must remain open and unmerged through the later phases.
- Historical Stage H/E status: The native goal resumed on 2026-07-24. Live Stage H proved
  that the prior shipped
  request projected 732 unit IDs but zero of 741 available evidence records and omitted required
  speaker, source, and structural ownership context. Approved manifest
  `consent_c988d3b944a81c177303d32f` exhausted both calls without producing a hierarchy. The
  failing-first typed-authority and repair-bound correction is now integrated and independently
  reviewed with no P0-P2. The user explicitly approved exceeding four total Day 1 submissions with
  at most two additional Stage H calls. V4 then used both calls and failed closed with
  `uncertain_membership`, creating no hierarchy or publication. The lifecycle returned through
  `Revise`; failing-first prompt/repair correction `70f60eb` passed independent exact-head rereview
  at `e33b773`. V5 then used both calls and failed closed with `semantic_reinterpretation`.
  Lock-policy correction `b97fa47` has repeated semantic `PASS` and passed independent exact-head
  review at `1adfe2d` with no P0-P2. The exact-head full functional suite passed 1,499 tests with
  five expected opt-in skips; the isolated M06 benchmark also passed. The user's latest
  standing authorization removes routine per-manifest approval pauses while exact identity,
  freshness, privacy, fingerprint, and resource-limit audits remain mandatory. Stage H v11 then
  exhausted two calls and failed closed with `uncertain_membership`, recording 483,973 input and
  5,015 output tokens; no hierarchy or publication exists. Its compact repair completed, proving
  the timeout correction. Prompt v11/policy v12/product v7/schema v4 bind the Python-proven
  evidence-complete and singleton-available invariant while retaining local fail-closed
  uncertainty validation. Focused tests pass 132/132; repeated semantic review is `PASS`, and
  independent exact-head review passed `6d99fd4` with no P0-P2. Stage E remains
  impossible until Stage H freezes.
  The prior
  `PR ready` result, product heads, screenshots, visible-order export, reviews, Release, and GitHub
  checks are historical rejected-baseline evidence only.
- The first uncontaminated source-first final review froze exact candidate `ac898b0` and returned
  `FAIL / CHANGES REQUIRED` before any oracle or mockup access. The original report was recovered
  verbatim from coordinator task history, including its P2, and retained in local private
  acceptance storage outside Git. Its five findings are published-reader lineage rejection,
  fundamental density/section-count failure, choice-after-consequence ordering, factual summary
  errors, and promotion of technical/generic material. Oracle comparison and browser acceptance
  remain paused.
- Revised semantic gate: [`PASS`](milestones/M15/SEMANTIC_REVIEW.md). The Stage H/Stage E
  `PASS` is revoked for future work. Phase 01 is complete; the Phase 02 coordinator froze the
  simple V2 contract/design, received `REVISE` on its first early review, applied the one bounded
  correction, and received same-task rereview `PASS` at `4d32f08` with no P0-P2.
  Historical v11 review evidence follows: the v11 uncertainty
  correction; independent exact-head review passed `6d99fd4` with no P0-P2. The earlier whole-scope
  `PASS` after transition commit `b5d08f5` is
  historical because its implementation audit missed
  the criterion-3 request-projection defect. The prior adjacent-only shared freeze
  `c768b19c8d9364db8f1987cb420e69ac0c2e535d` is also historical. The corrected exact-head review
  passed at `a7997b1`; the equivalent full chain is integrated through `a7cdf9f` and passed fresh
  coordinator gates.
- Historical native goal: tracked history records goal/task
  `019f8014-e8f9-7af3-a54f-8cc3a7e7149c` for the rejected whole-scope Stage H/Stage E objective.
  It is not the active goal. Current Phase 02 goal/task
  `019f9676-c357-7803-a891-f03782bbb8ee` is recorded above and remains active through
  implementation, integration, acceptance, review, and checkpoint push.
- Interrupted-state recovery: integration HEAD `1c66cc3312e2af322f405c161df47a495cce617f`,
  branch/upstream divergence 48 ahead and zero behind, 13 modified tracked files, and two v4
  resources were verified. The v4 SHA-256 values matched the supplied checkpoint. The supplied
  tracked-diff hash `7c85c813de1a8cb8f522d9b4adde820fdfd79f4a` did not match the current Git blob
  hash `8d4f76b20a52509b5912557376c7434cce27e560`; no prior track was active, the file set
  matched, and the actual state was preserved rather than normalized.
- Safety isolation: only the explicit 13 tracked files plus two v4 resources were committed to
  local unpushed branch `codex/m15-1-interrupted-safety-20260723` at
  `9aa6b7cb1d26115c1a35b10492233633cf7a00f5` (455 insertions, 143 deletions). The scan found no
  secret/private-derived content; the sole private-reference match was a generic prompt prohibition.
  `.playwright-cli/`, `docs/handoffs/`, `output/`, and `tmp/` remain untouched. A separate clean
  worktree at `C:/Users/prave/.codex/worktrees/m15-1-revise-20260723/Renpy` holds the existing
  integration branch at corrected provider-free head `5d782ce`.
- Required task topology after the revised shared freeze: separate visible Track A (hierarchy
  validation/compiler), Track B (batched provider lifecycle/persistence), and Track C (compact
  projection/UI) tasks/worktrees, each with an independent exact-head reviewer, then fresh blind
  membership and final source-first/private-reference reviewer tasks. Bounded worker and reviewer
  branches/worktrees are allowed; no replacement integration branch, second PR, or new milestone
  is. The coordinator owns ordered integration and all private evaluation. Prior tasks are history:
  - Track A task `019f84a1-897e-7a91-a622-fc00f5a10d72`, worktree
    `C:/Users/prave/.codex/worktrees/dc1a/Renpy`, branch `codex/m15-1-track-a`;
  - Track B task `019f84a1-897f-7953-a1f6-fa043410bcee`, worktree
    `C:/Users/prave/.codex/worktrees/b547/Renpy`, final correction branch
    `codex/m15-1-product-path-backend`;
  - Track C task `019f84a1-897b-7a40-ba52-1f26d6dca090`, worktree
    `C:/Users/prave/.codex/worktrees/bb69/Renpy`, branch `codex/m15-1-track-c`.
- Revised provider-free implementation: Track A task `019f8f26-df67-77a1-86f1-2000fe214e43`
  passed exact-head review at `1b5175bd`; Track B task
  `019f8f26-dec1-7032-9da5-127c20a6040f` passed at `8cf32e9`; Track C task
  `019f8f26-dec1-7032-9da5-125cdf9a41da` passed fresh review at `34aef7c`. Independent integrated
  architecture task `019f8f33-a13d-7d22-b0f3-d9ca407e60df` passed the original correction tree at
  `6a37903` and the final exhausted-run/lost-CAS correction at exact head `7e20a27`, both with no
  P0-P2. The final reviewed additive chain is integrated as `83de774`, `5cd91ec`, `e6f8816`,
  `a4d0b63`, `d4b9d40`, and `5d782ce`; integrated `src/`/`tests/` are identical to the reviewed
  tree. Coordinator verification records 321 M15 tests passed with three expected opt-in/private-
  fixture skips, 75 cross-milestone web/API tests, 19 browser asset-contract tests, workflow
  contract, strict mypy over 116 source files, Ruff, dependency/JavaScript/JSON, diff/privacy/
  frozen-resource checks, and nine synthetic acceptance cases with zero provider calls and zero
  game execution. Fresh Stage H/E, private semantic review, real Chrome, Release, screenshots/user
  approval, push/checks, and PR readiness remain pending.
- Stage H exhausted-run correction: the supported product path opened an isolated copy of the
  exact private Day 1 project and prepared sterile manifest `consent_da4aecc72b5dfb3fb4523c27`
  for build `whole_scope_build_83b5644d73e7b0ba4e026b5f`; the user approved that exact manifest.
  Attempt 1 transmitted and timed out at 300 seconds. Exact retry attempt 2 returned after about
  297 seconds; cumulative accounting is two calls/reservations, 87,813 input tokens, and 16,301
  output tokens. Full Python validation then rejected the schema-valid response because its cluster
  membership was not representable by the existing assembler. Durable state incorrectly remained
  `validated` with no hierarchy hash or failure code, so this is a live-path P1 rather than Stage H
  acceptance. Source/archive hashes and timestamps remain unchanged; Stage E was not prepared or
  called. The manifest is exhausted and no third call is allowed. Bounded correction task
  `019f8f26-dec1-7032-9da5-127c20a6040f` moved exact authority validation inside durable Stage H
  acceptance, atomically quarantines legacy invalid results, uses whole-scope product identity v2
  with a finite 900-second timeout, and fails closed after bounded lost-CAS reconciliation. The
  same independent architecture reviewer passed exact final head `7e20a27` with no P0-P2; the
  additive chain is integrated through `5d782ce`. Coordinator verification records 321 M15 tests
  passed with three expected skips, 75 cross-web/API, 19 browser asset-contract tests, workflow
  contract, strict mypy over 116 source files, Ruff, dependency/JS/JSON, frozen-resource/privacy/
  diff checks, and nine zero-provider/zero-game synthetic cases. The exhausted copy remains audit
  evidence; a fresh exact acceptance copy must be prepared without submission before a new Stage H
  manifest is presented. The outside-Git failure artifact SHA-256 is
  `ADFE0EFF8E2311AA11AAC14624589AA7B3F1BE2803A938E1ABD7C02FC1A2532C`.
- Fresh Stage H v2 execution: accepted baseline
  `output/playwright/m15-private-final/corrected-working-copy.rsmproj` was copied to fresh isolated
  `output/m15-1-whole-scope-acceptance-v2-20260723/msday1-working.rsmproj`. The shipped product API
  prepared manifest `consent_c988d3b944a81c177303d32f` for build
  `whole_scope_build_0f843c9c1ef607c4de085bcc`, one logical hierarchy job, provider
  `gpt-5.6-sol` Medium with fast mode off, maximum two calls, concurrency one, and a finite
  900-second timeout. Preparation recorded zero provider constructions, reservations, calls, and
  tokens; source, original archive, and accepted baseline fingerprints remained unchanged.
  Outside-Git preparation artifact SHA-256 is
  `32B8A7C5F98D3D6EB8D80D66051B89B003B052619BF90718D09514B032E491E2`. The user approved that
  exact manifest. The run consumed both calls/reservations (87,813 input tokens, 15,553 output
  tokens, 285,516 accounted ms); the first response failed validation and the targeted repair ended
  `provider_process_failed`. Durable state is failed with no hierarchy, logical result, cache, or
  publication. Source/archive/baseline fingerprints remain unchanged and Stage E was not prepared.
  The manifest is exhausted. Audit artifact SHA-256 is
  `4CE78DCA1E5674B47BA44145BDAB39D016A526546E33F245554927093E6E1B6D`.
- Stage H criterion-3 projection correction: bounded worker branch
  `codex/m15-1-stage-h-payload` used failing-first commits `485aad8`, `0c6cc34`, and `d0a4d3a`.
  The first exact-head review failed `a01ba6b` with two P1s: same-shaped payload values were not
  bound to typed authority, and a worst-legal retained repair could exceed one million bytes. The
  corrected v2 input/response/prompt, repair policy v2, and product identity v4 now construct the
  only accepted payload from typed units/evidence/ordered hard locks and bound groups, keys,
  reasons, and warnings consistently. The same reviewer passed exact head `a7997b1` with no P0-P2.
  Integrated commits `117720b`, `6bcdb73`, `1d155f9`, `3c490b0`, and `a7cdf9f` have `src/` and
  `tests/` identical to the reviewed tree. Exact sizing: 642,416-byte payload; 644,522-byte initial
  envelope; 645,071-byte authority repair; 917,391-byte worst legal retained repair; 82,609 bytes
  minimum headroom. Coordinator gates: 341 M15 passed/3 expected skips, 75 cross-web/API, 19 browser
  asset-contract passed/2 expected skips, 44 workflow, Ruff, strict mypy over 115 source files,
  dependency/JS/JSON/diff/privacy/frozen checks, and nine zero-provider/zero-game synthetic cases.
  Source/archive/accepted-baseline fingerprints remain unchanged. Outside-Git correction artifact
  SHA-256 is `6F22E9C70FB27047A9D9159B7BAC9896A6FB37CE395DF259ACD374A78375FFFF`.
- Fresh corrected Stage H v3 preparation: the unchanged accepted baseline was copied to isolated
  `output/m15-1-whole-scope-acceptance-v3-20260723/msday1-working.rsmproj`. The shipped product
  controller prepared build `whole_scope_build_c9f828ed30398aef1f2a2555` and exact manifest
  `consent_0694aa9eeb81df6b0a0a36cb`, expiring `2026-07-23T21:10:59.022751Z`. Identity is bound to
  correction hash `7fb38163...ed39`, prompt hash `2f48bada...a7b2`, schema hash
  `87a4c4e4...a05b`, source hash `e66a736f...728d`, authority hash `ff90b999...a778`, and input hash
  `ed207984...ae9c`; provider is requested/resolved `gpt-5.6-sol`, Medium, fast off. Limits remain
  one logical job, two calls, concurrency one, 1,000,000 input bytes, 2,000,000 output bytes, and
  900 seconds. Initial envelope is 644,543 bytes. Preparation constructed no provider and recorded
  zero reservations/calls/tokens; source/archive/accepted baseline remain unchanged. Artifact
  SHA-256 is `5F21BFF6D6B2B954521064F3A515C1ACFFC7CFB71D8740A23B9F121852D81789`.
  Transmission requires two separate explicit approvals: exceed four total Day 1 submissions and
  approve this exact manifest. Stage E remains unauthorized.
- Fresh corrected Stage H v4 preparation: after the native goal resumed, the user explicitly
  approved exceeding four total Day 1 submissions with at most two additional Stage H calls. The
  expired v3 consent was not used. The unchanged accepted baseline was copied to isolated
  `output/m15-1-whole-scope-acceptance-v4-20260724/msday1-working.rsmproj`; the shipped controller,
  guarded by a provider factory that raises if constructed, prepared exact manifest
  `consent_5181073c41933f07c2ccc887` for unchanged build
  `whole_scope_build_c9f828ed30398aef1f2a2555`, expiring `2026-07-24T14:25:53.093664Z`.
  Source, authority, correction, input, prompt, schema, provider, privacy, job, and resource-limit
  identities exactly match the reviewed v3 preparation. Initial envelope is 644,547 bytes; durable
  combined submissions, provider constructions, reservations, calls, tokens, logical records,
  hierarchy, and publication remain zero/absent. Source/archive/accepted-baseline fingerprints are
  unchanged. The working copy is 12,124,160 bytes at SHA-256
  `2349fe6c6a9e7f0bace214b71990bb4db8bd78f480ba145dcc74aa707513aeee`; preparation artifact
  SHA-256 is `5DD286EE293A67EC6567E99A2F439EDEEBB384ADFF0A18091C7B88F7B16A448C`.
  The manifest executed while valid and is now exhausted. It consumed two submissions, failed
  `uncertain_membership`, recorded 482,491 input tokens and 14,385 output tokens, and produced no
  hierarchy, logical record, or publication. Failure artifact SHA-256 is
  `E68A26B5434116DF1463445CF1EC4994D2A797B74CE6A4722C37C1436852269B`; source/archive/accepted
  baseline remained unchanged. The prompt/repair contradiction found from this failure is corrected
  at `70f60eb` with new prompt and repair-policy identities; old consent cannot be reused.
- Fresh corrected Stage H v5 preparation: after exact-head review `PASS` at `f44ab19`, the unchanged
  accepted baseline was copied to isolated
  `output/m15-1-whole-scope-acceptance-v5-20260724/msday1-working.rsmproj`. A provider-forbidden
  preparation created exact manifest `consent_14655be0e14020371cdf104f`, expiring
  `2026-07-24T15:12:27.164065Z`, for build `whole_scope_build_f976f648d0f606eaa1b74c0b`.
  It binds prompt `m15-whole-scope-hierarchy-prompt-v3`, repair policy
  `m15-whole-scope-targeted-repair-v3`, response schema v2, prompt hash
  `3168131c5200e2e2f0ede5e118636f6914a61c2c751430d43103e0b70d33bae4`, input hash
  `8e3c4659a61ba0cd07ae57d90df41cb025974c4bc26b7a68e522cff6e149081a`, and the unchanged
  authority/source/schema/provider/privacy/limit identities. Initial envelope is 644,718 bytes;
  provider constructions, reservations, calls, tokens, records, hierarchy, and publication are
  zero/absent. Source/archive/accepted baseline are unchanged. Preparation artifact SHA-256 is
  `84957AF6D27D1B4918D4A7B7A336C90655791BEAA73A82965B69536A6EBCD5E4`. The user's standing
  authorization permits exact bounded execution without another approval pause.
- Stage H v5 execution and lock-policy correction: exact manifest
  `consent_14655be0e14020371cdf104f` executed while valid, consumed two calls, and failed closed with
  `semantic_reinterpretation`. It recorded 497,401 input tokens and 30,020 output tokens but no
  hierarchy, logical record, publication, or Stage E activity. Source/archive/accepted baseline
  remained unchanged. Result artifact SHA-256 is
  `DFD1533DFD4CEE3F5DF53F5E5FD9E9EA36D398EBBAFDFBE0B18D57B83B3F5933`. The lifecycle returned to
  `Revise`. A failing-first test proved hierarchy repair was still described with summary-specific
  scalar/claim lock wording. Commit `b97fa47` explicitly maps internal beat, cluster, and editorial
  record locks to their complete output arrays, preserves byte-for-byte Python enforcement, and
  bumps the exact repair-policy identity to v4. Expanded focused 107/107, Ruff, strict mypy, 1,499
  functional tests/five expected skips, and the isolated M06 benchmark pass. Repeated semantic and
  independent exact-head review are `PASS` at `1adfe2d`; fresh zero-submit preparation is next.
- Fresh Stage H v6 preparation: the unchanged accepted baseline was copied to isolated
  `output/m15-1-whole-scope-acceptance-v6-20260724/msday1-working.rsmproj`. Provider-forbidden
  preparation produced exact manifest `consent_19347f6e215c44d3bb8ae6ca`, expiring
  `2026-07-24T15:50:07.902526Z`, for build `whole_scope_build_f976f648d0f606eaa1b74c0b`. It binds
  whole-scope repair policy v4, prompt hash
  `2a6beda45fb9d17449d39e20d163e13708d4ae2f2215b748c50ab0800e3cd74e`, input hash
  `8e3c4659a61ba0cd07ae57d90df41cb025974c4bc26b7a68e522cff6e149081a`, and unchanged source,
  authority, schema, provider, privacy, and two-call/resource limits. The 644,718-byte initial
  envelope fits; provider constructions/reservations/calls/tokens are zero; source/archive/accepted
  baseline are unchanged. Preparation artifact SHA-256 is
  `C3B568547C71C953E206A8E8C9F768E7ACF235CFFED27843B27369E98A4D360B`. Standing authorization
  permits exact bounded execution without another routine pause.
- Stage H v6 execution and ambiguity-threshold correction: exact manifest
  `consent_19347f6e215c44d3bb8ae6ca` executed while valid, consumed two calls, and failed closed with
  `uncertain_membership`. It recorded 482,652 input tokens and 31,690 output tokens but no
  hierarchy, logical record, publication, or Stage E activity. Source/archive/accepted baseline
  remained unchanged. Result artifact SHA-256 is
  `320E1324B438AF93526B62F18417872E38E11DDDC6B82DFEBF40C623945DF9DC`. The lifecycle returned to
  `Revise`. Repeated failures showed that ordinary editorial ambiguity was still being treated as
  terminal uncertainty. Commit `b81dbad` advances hierarchy prompt v4 and repair policy v5: normal
  ambiguity must use confidence/warnings or a conservative singleton beat, while nonempty
  `uncertain_unit_ids` remains reserved for missing evidence or structural impossibility and is
  still rejected by Python. Focused 108/108, Ruff, and strict mypy pass; repeated semantic review is
  `PASS`. Independent rereview passed exact head `dc5a631` with no P0-P2 after the direct identity
  regression proved prompt-version changes alter consent job IDs and identity hashes while a
  repair-policy-only change remains manifest-only. The exact-head functional suite passed 1,500
  tests with five expected opt-in skips; the isolated M06 benchmark, Ruff, and strict mypy over
  115 source files also passed. That checkpoint was superseded by the v7 run below.
- Stage H v7 execution and invalid-beat repair correction: zero-submit preparation from the
  unchanged accepted baseline produced exact manifest `consent_0ef74a1324d245a21acfb2c5`, build
  `whole_scope_build_957fb7bf9cb9320865df6387`, prompt hash `dbc80380...2094`, and input hash
  `01e88432...5ae7`. Preparation recorded zero provider constructions/calls/reservations/tokens;
  the 645,042-byte envelope fit and all protected fingerprints remained unchanged. Preparation
  artifact SHA-256 is `25909495CE551C80A3651EEF19119C5BB980E26DE6E40EE01CA5C81B029F356B`.
  The exact valid manifest consumed two calls, 482,745 input tokens, and 29,299 output tokens, then
  failed closed with `invalid_beat_group`. It created no hierarchy, logical record, publication,
  or Stage E activity; protected fingerprints remained unchanged. Result artifact SHA-256 is
  `FF2682149438490CD5035C79057DAC4C67E4F78AC5469C5A7554C863F900D532`. The lifecycle returned
  through `Revise`. Failing-first correction advances prompt v5 and consent-bound repair policy
  v6 with explicit per-group unique-ID, trimmed-field, length, confidence, warning, and exact-field
  constraints while leaving Python rejection unchanged. Focused 108/108, Ruff, strict mypy over
  115 source files, JSON parsing, and diff checks pass. Repeated semantic review is `PASS`;
  independent exact-head rereview passed `6ab84ab` with no P0-P2. The exact-head functional suite
  passed 1,500 tests with five expected opt-in skips, and the isolated M06 benchmark passed. Fresh
  zero-submit Stage H preparation was the v8 checkpoint below.
- Stage H v8 execution and assembler-context projection: zero-submit preparation produced exact
  manifest `consent_3c1c64df0020fdb6f6733561`, build
  `whole_scope_build_fb850b343ee985493ff09da4`, prompt hash `45f4d55e...8d0c`, and input hash
  `e7ca9f45...a55f`. It recorded zero provider constructions/calls/reservations/tokens; the
  645,603-byte envelope fit, and protected fingerprints remained unchanged. Preparation artifact
  SHA-256 is `A28D8BE69DE6FBBA7F77E3F3022FB07B4BE17393B7CD748209FDD4DEDE223F7B`.
  The exact valid manifest consumed two calls, 482,977 input tokens, and 32,287 output tokens, then
  failed closed with `hierarchy_not_representable`. It created no hierarchy, logical record,
  publication, or Stage E activity; protected fingerprints remained unchanged. Result artifact
  SHA-256 is `6334E0837698FDE14013FC2BF200A3B62EAF2940E7EADC9B5A29DC110FCA385E`.
  Provider-free inspection found 732 units, three progression states, and two transitions; the
  assembler uses progression in major-cluster context, but Stage H input v2 omitted it. The
  lifecycle returned through `Revise`. The first exact-head review found one P1: assembler choice
  ownership overrides normal context splits, but the request lacked the owning parent/continuation
  grouping. Corrected input v5, prompt v8, and consent-bound repair policy v9 project three compact
  exact progression runs and deduplicated authority-bound inclusive unit-ID ranges on existing
  choice-ownership hard locks, require each expanded range to share one
  major cluster with precedence over context changes, and enforce that invariant in Python. No
  topology ID or prose is added. The serialized differing-lane parent/arms/rejoin case round-trips,
  while a context-split proposal fails closed. Focused M15.1/product 110/110 and combined hierarchy
  128/128 pass; Ruff, strict mypy over 115 source files, JSON parsing, and diff checks pass. The
  exact private canonical payload is 643,032 bytes under the 660,000-byte typed-payload ceiling.
  Repeated semantic review is `PASS`; independent exact-head rereview passed `19258ba` with no
  P0-P2. The exact-head full suite passed 1,503 tests with five expected opt-in skips; both isolated
  M06 scale checks and static gates passed.
- Stage H v9 execution and typed-repair correction: exact manifest
  `consent_8f0c4d16185f61f8d2e194ee` executed while valid, used two calls, 483,853 input tokens,
  33,824 output tokens, and failed closed with `hierarchy_authority_invalid`. No hierarchy, logical
  record, publication, or Stage E exists; protected fingerprints are unchanged. Result artifact
  SHA-256 is `4F59C6756C62536FEA238654283A76A80F57080D0F6BA962C4F09481E5878272`.
  Provider-free postmortem found the generic authority code discarded all schema-valid beats and
  clusters before repair. Prompt v9, repair policy v10, and product identity v5 introduce typed
  `choice_cluster_split`: valid beats remain locked byte-for-byte, only clusters are unlocked, and
  merge guidance names exact inclusive choice ranges and precedence. Combined provider-free tests
  pass 130/130; Ruff and strict mypy over 115 source files pass. Repeated semantic review is `PASS`;
  independent exact-head rereview passed `725d44f` with no P0-P2. The exact-head full suite passed
  1,505 tests with five expected opt-in skips.
- Stage H v10 execution and compact-repair correction: exact manifest
  `consent_96444c68c97ce0d025982e71` exhausted both reserved slots. The first response completed
  with 241,792 input and 17,457 output tokens; the typed cluster-only repair then timed out at its
  900-second limit. Durable state is failed with `timeout`; no hierarchy, logical record,
  publication, or Stage E exists, and protected fingerprints remain unchanged. Result SHA-256 is
  `9EF48ED5BE124D03A808392BB9D330B9BFCF5755EC0067575B6441E7E761A03F`.
  The repair still required retransmitting all 732 locked beats. Prompt v10, repair policy v11,
  product identity v6, and new response schema v3 (with immutable v2 preserved) now permit a choice-only repair to
  return `beat_groups: []`; Python rehydrates the exact validated locked beat objects before lock
  matching and complete authority validation. Combined provider-free tests pass 132/132; Ruff and
  strict mypy over 115 source files pass. Repeated semantic review is `PASS`; independent exact-head
  rereview passed `76ef7fc` with no P0-P2. The exact-head full suite passed 1,507 tests with five
  expected opt-in skips. Fresh V11 zero-submit preparation is next.
- Stage H v11 execution and evidence-complete uncertainty correction: exact manifest
  `consent_195336f83e426fb222fecc19` exhausted both slots and failed closed with
  `uncertain_membership`, recording 483,973 input and 5,015 output tokens. No hierarchy, logical
  records, publication, or Stage E exists; protected fingerprints remain unchanged. Result
  SHA-256 is `0F36D04F16370FB45F69400E413DA73E48648609EC11F5DB77DE31286CC44703`.
  The compact repair completed. Python preparation rejects any unit without exact transient
  evidence, and a conservative singleton beat is always structurally available. Prompt v11,
  repair policy v12, product identity v7, and immutable successor schema v4 therefore require
  `uncertain_unit_ids: []` at provider transport. Historical/fake nonempty uncertainty is still
  rejected locally. Focused tests pass 132/132; repeated semantic review is `PASS`, and independent
  exact-head review passed `6d99fd4` with no P0-P2. Fresh V12 zero-submit preparation is next.
- Dispatch policy: every visible task uses `gpt-5.6-sol` with High reasoning. The creation surface
  has no fast-mode selector, so fast mode is unavailable/unverified. The live product acceptance
  profile remains separately locked to `gpt-5.6-sol`, Medium reasoning, fast mode off.
- Historical adjacent-only verification: 174 M15 tests passed with two expected opt-in browser skips; 169
  web/M10/M11 compatibility tests and both enabled Chrome suites (10 tests) passed. Ruff, strict
  mypy over 114 source files, JavaScript syntax, whitespace, and the private-reference diff scan
  passed. Track A reviewed head `09062370`, Track B final product-path head `ca048973`, and Track C
  final compatibility head `61a3eef` had no unresolved P0-P2.
- Private preflight: source SHA-256
  `14aa44ed95dec5402dfb02a1c4e01e63b3f3e329cf04fec37b04edebb5d588a6`, 42,818 bytes,
  `2026-07-20T14:57:21.9287268Z`; archive SHA-256
  `053abb13454180a2cf9b0aa762e33deda98cf027d9c1e39082f5795982720303`, 2,140,282 bytes,
  `2026-07-03T01:11:16Z`. Both matched the ignored private manifest. Final before/after proof remains
  required; private source, oracle, handoff, mockups, and output artifacts stay outside Git.
- Historical provider state: approved boundary manifest `consent_8a1657a8917261da9d8082a4` was superseded
  in-process by matching effective manifest `consent_647d928f95ccc14b1ca02bb4` and consumed by
  94 bounded provider submissions. Zero jobs validated: 93 failed `output_schema_rejected` because
  Codex CLI 0.144.0 rejects the schemas' `uniqueItems` keyword, and one failed
  `provider_unavailable`; no workflow tokens were recorded. Source, seed, and M10-M13 authority
  rows remained unchanged. Four versioned successor response schemas now remove only that
  unsupported keyword while preserving strict local uniqueness validation and changing job/cache/
  consent identity. Those records remain readable but are stale for Stage H/Stage E. The current
  resumption and historical consents do not authorize either revised provider stage; each exact
  manifest must be presented for explicit consent.
- Versioned-schema live retry manifest `consent_7857c66fd76b25a58a6b4713` proved the schema fix
  across 59 validated windows with zero job errors, then its 15-minute consent expired before the
  60th reservation, leaving 35 pending. The source, archive, and M10-M13 authority rows remained
  unchanged. Product manifests now use a one-hour window, and mid-run expiry records a durable
  `consent_expired` failure instead of escaping with a stale `boundaries_running` state. Fresh
  boundary and summary manifests reconcile exact newly completed jobs, usage, and uncheckpointed
  ledger reservations before cache replay, with per-manifest reservation checkpoints preventing
  double counting across repeated rotation. Cross-process hardening additionally fingerprints
  terminal records, preserves advanced lifecycle phases, and blocks overlapping same-stage
  manifests through consent expiry plus provider timeout. The correction independently passed
  with no P0-P2; 196 M15 tests passed with two expected opt-in browser skips, plus Ruff, strict
  mypy over 114 source files, and whitespace checks. Live boundary records are 94/94 validated;
  one recovery-only product preparation must checkpoint the final 94/94 accounting.
- Existing untracked `.playwright-cli/`, `docs/handoffs/`, `output/`, and `tmp/` content remains
- Historical live semantic production completed at `e925afd9b9f7fb83f44518e67a6eca5f14655f30`.
  Boundary checkpoint evidence records 94/94 validated jobs; checkpoint manifest/result SHA-256
  are `817889a6f46a02780013ced0cb7e886cdd46765ed075d97a7463654edb26bc29` and
  `d448ed9688e6bde4a7b2542647513ce7da2892bb35d3076a779e68dd354eca66`.
  Summary manifest `consent_710e992d5a0f47e3108351de` completed 161/161 validated jobs and
  published hash `139c690ea9d3ddd9b39786b6fbf65783890c21461c611ad0f617ae83af511c8f`.
  Its manifest/result SHA-256 are `28f8612db806768b463543b0ac5ab0afcad93aadfd9c69ad327ec1d0c6cabe30`
  and `557745d7246a532ef7c8430135c6d2d6e8831b3028fe39d5cee4e590524fc32c`.
  Final accounting is exactly 529 provider calls/reservations; source, archive, and M10-M13
  authority rows remained unchanged. Recovery, race-fencing, and combined-repair corrections pass
  203 M15 tests with two expected browser skips, Ruff, strict mypy over 114 files, and independent
  review with no P0-P2. Final private review, browser/user acceptance, Release, and PR readiness
  remain pending. None of this is current Stage H/Stage E acceptance proof.
- Existing untracked `.playwright-cli/`, `docs/handoffs/`, `output/`, and `tmp/` content remains
  preserved. M14, full-game work, game/creator execution, PR merge, and unrelated scope remain
  deferred or excluded.

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
