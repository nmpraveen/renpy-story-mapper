# M15.1 semantic review

Date: 2026-07-24

Architectural correction base: `1c66cc3312e2af322f405c161df47a495cce617f`

Prior decision: 2026-07-21 `PASS`, revoked because it made adjacent-gap classification the primary
AI semantic task.

Decision: PASS

## Review result

The observable M15.1 done condition remains unchanged: the supported product must produce a compact,
chronological, evidence-linked Prologue/Day 1 Story Map while M10/M11 retain topology and evidence
authority. The existing native goal, integration branch, and open unmerged PR #26 continue.

The internal semantic method is revised. Fine narrative units and exhaustive adjacent-gap records
remain deterministic compatibility structures, but tiny gap votes are no longer the provider's
primary task. Stage H proposes a coherent whole-scope editorial hierarchy using existing
authority-bound fine-unit IDs. Python validates and compiles that proposal into exhaustive gap
decisions before the existing assembler runs. Stage E then produces a whole-scope editorial batch
for frozen existing subjects. Provider output remains non-authoritative.

The lifecycle transition was recorded at `b5d08f567132f8bd2743a39187e57dffe18b3a00`. The
coordinator then reread the reconciled authority set and repeated the gate against the complete
revised contract. That `PASS` is now historical: live Stage H acceptance proved that the shipped
request projection carried 732 unit IDs but zero of the 741 available evidence records, while its
unit records omitted speakers, source IDs/locators, lane/call/loop ownership, and other required
structural anchors. This violates `GOAL.md` criterion 3 and leaves the provider unable to perform a
coherent semantic grouping from the transmitted request alone.

The approved manifest `consent_c988d3b944a81c177303d32f` is exhausted after two calls. The first
response failed product validation and the automatic targeted repair ended
`provider_process_failed`; no hierarchy or publication was created and Stage E was untouched.

The bounded correction used genuine failing-first commits for missing evidence, mutable same-shape
authority, and an oversized worst-legal retained repair. The first independent exact-head review
returned `FAIL` with those last two P1s. The worker then moved canonical payload construction behind
typed `FineNarrativeUnit`, `SemanticEvidenceRecord`, and ordered `HierarchyHardLock` inputs,
versioned the response/repair/product identities, and imposed matching schema/domain bounds. The
same reviewer passed exact head `a7997b13d6a4b6d91edcacbf1182c526c709cc3b` with no P0-P2. The
full chain is integrated through `a7cdf9ffbfe2e6d1a884f9f794f347862bcca66b`.

Exact provider-free sizing is 642,416 payload bytes, 644,522 initial-envelope bytes, 645,071
authority-repair bytes, and 917,391 bytes for the worst legal retained repair, leaving 82,609 bytes
below the one-million-byte ceiling. Coordinator gates passed with 341 M15 tests/three expected
skips, 75 cross-web/API tests, 19 browser asset-contract tests/two expected skips, 44 workflow
tests, Ruff, strict mypy over 115 source files, dependency/JavaScript/JSON/diff/privacy/frozen
checks, and nine synthetic cases with zero provider calls and zero game execution.

## Requirements mapping

| Requirement | Revised interpretation | Contract location |
|---|---|---|
| Human-readable chronology | A coherent bounded day/chapter is the semantic unit of work; the final map remains five top-level sections with local choices | `GOAL.md` criteria 3-8 and 14-17 |
| Fine semantic granularity | Every authority-bound fine unit remains exact and every legal adjacent gap remains represented internally | Criteria 1-3 |
| Non-authoritative AI hierarchy | AI may group only existing unit IDs and use temporary proposal keys; it cannot invent authority IDs or topology | Criteria 3-5 and 9 |
| Complete deterministic validation | Python proves identity, exact coverage, order, contiguity, ownership, and structural locks, then derives stable IDs and compiles gap decisions | Criteria 5-6 and 9 |
| Batched editorial language | Stage E returns one logical record per existing frozen beat, cluster, and meaningful choice, citing existing evidence IDs only | Criteria 7-8 |
| Two exact live gates | Stage H and Stage E have separate exact consents, durable state, accounting, recovery, and replay | Criteria 10-13 |
| Bounded provider use | Day 1 expects two successful submissions and allows no more than four total without new approval | Criterion 12 |
| Compact accessible UI | Normal-flow vertical HTML, meaningful collapsed summaries, local choices/rejoins, 100%/200%, exact evidence | Criteria 14-17 |
| Privacy and immutability | Private targets and external comparison material never enter prompts, runtime fixtures, or Git | Criterion 19 and exclusions |
| Review and release | Separate visible tracks/reviewers, blind membership/final reviews, user screenshot approval, one final Release | Criteria 18 and 20 |

## Architecture boundaries

- `src/renpy_story_mapper/narrative_map/` remains the M15 domain boundary.
- Track A owns Stage H contracts, provider-independent hierarchy validation, hierarchy-to-gap
  compilation, stable authority-derived IDs, deterministic assembly integration, and generalized
  hard-lock/nested-choice fixtures.
- Track B owns Stage H/Stage E prompts and schemas, exact manifests/consents, sterile transport,
  logical-record versus transport-batch provenance, validation, targeted repair, cache identity,
  accounting, cancellation, recovery, publication, reopen, zero-submit replay, and historical
  record compatibility.
- Track C owns compact chronological projection, meaningful collapsed summaries,
  choice-before-consequence ordering, stable arm presentation identities, complete arm evidence,
  nested local choice/rejoin display, validated-role filtering, normal-flow HTML, and browser
  evidence mapping.
- M10/M11 remain sole authority for connectivity, choices, captions, arm order, rejoins,
  requirements, effects, calls, loops, endings, locators, and source evidence.
- Temporary proposal keys, titles, summaries, characters, presentation roles, claims, confidence,
  reasons, and warnings are allowed non-authoritative outputs. Grouping may reference only existing
  authority-bound unit/subject IDs; claims may cite only existing evidence IDs.
- Private source expectations, oracle content, mockups, and Gemini/Grok outputs are coordinator-only
  evaluation material and cannot enter Git, provider input, generalized fixtures, or blind-review
  context.

## Expected implementation and tests

| Area | Expected surfaces | Required focused evidence |
|---|---|---|
| Shared freeze | Stage H/Stage E contracts, schemas, synthetic examples, failing-first tests | Exact coverage, order/contiguity, hard locks, proposal-key non-authority, hierarchy compilation, batched records, four-call ceiling |
| Track A | Contracts, validation/compiler, assembler integration | Linear/split/nested/call/loop/lane/terminal/unresolved fixtures and fail-closed malformed proposals |
| Track B | Prompt/schema resources, lifecycle/service/persistence/provider adapters | Separate consent identity, logical/transport provenance, repair ceiling, cancel/recover/reopen, historical stale compatibility, zero-submit replay |
| Track C | Projection, API, HTML/JS/CSS and browser tests | Five-section/4-choice/8-arm/<=32 contracts, ordering, arm evidence, role filtering, Detail/Evidence, 100%/200% |
| Integration | Fake-provider end-to-end and compatibility | Complete Stage H to Stage E publication, stable hashes, reopen/replay, no authority mutation or private leakage |
| Final acceptance | Blind membership/final review, real browser, Release/package, PR checks | Required captures, user approval, no P0-P2, exact passing pushed head on open unmerged PR #26 |

## Evidence plan

- Preserve the interrupted v4 attempt on a local unpushed safety branch and do revised work from a
  separate clean worktree at integration HEAD.
- Freeze the revised shared schemas, generalized examples, and genuinely failing-first tests on one
  clean integration commit only after this semantic gate passes.
- Dispatch separate visible Track A/B/C worktrees from that exact shared head. Bounded worker and
  reviewer branches are allowed; no replacement integration branch, second PR, or new milestone is.
- Require an independent exact-clean-head reviewer for every track and do not integrate unresolved
  P0-P2 findings.
- Complete fake-provider, compatibility, reopen, zero-submit replay, architecture review, and exact
  identity freeze before presenting Stage H for consent.
- Review frozen Stage H membership blind before preparing the separately consented Stage E batch.
- Keep all historical 94-boundary/161-summary records readable but stale for the revised production
  identity; never relabel their 529 calls as current proof.
- Freeze a final source-first review before any private comparison, then obtain real-browser and user
  visual approval before the single final Windows Release/package gate.

## Resolved conflicts

- The user explicitly changed only M15.1's internal semantic method; the observable done condition
  and acceptance floor are unchanged.
- The native goal was recreated at the user's instruction on 2026-07-23 and remains active on task
  `019f8014-e8f9-7af3-a54f-8cc3a7e7149c`.
- “No another M15 branch” means no replacement integration branch, second PR, or new milestone.
  Required bounded worker and reviewer branches/worktrees remain allowed.
- Provider proposal keys and editorial text are non-authoritative. Only referenced input unit,
  subject, and evidence IDs must already exist.
- Repository dispatch requires `gpt-5.6-sol` with High reasoning for every visible implementation,
  architecture, integration, debugging, correctness, security, semantic, and review task. The task
  surface has no fast-mode selector, so fast mode is unavailable/unverified. The live product
  profile remains `gpt-5.6-sol`, Medium reasoning, fast mode off.
- On 2026-07-24 the user granted standing authorization for all remaining M15.1 gates and bounded
  provider runs through completion. Exact manifests, freshness, identity, privacy, and resource
  limits remain mandatory audit controls, but routine per-manifest approval pauses are removed.

## 2026-07-24 uncertainty-repair correction

Fresh v4 manifest `consent_5181073c41933f07c2ccc887` executed while valid under the user's exact
authorization. It used one initial Stage H call and one targeted repair, then failed closed with
`uncertain_membership`: 482,491 input tokens, 14,385 output tokens, and no hierarchy, logical
record, publication, or Stage E activity. Source, archive, and accepted-baseline fingerprints
remained unchanged. The failure artifact SHA-256 is
`E68A26B5434116DF1463445CF1EC4994D2A797B74CE6A4722C37C1436852269B`.

The lifecycle returned to `Revise`. The validator correctly rejects nonempty
`uncertain_unit_ids`, and the semantic lock correctly unlocks rejected hierarchy groups; Python
does not clear uncertainty. The defect was a prompt/repair-policy contradiction: the initial
prompt invited uncertain IDs while the generic targeted-repair instruction did not explain that
`uncertain_membership` cannot produce an accepted hierarchy. A failing-first regression reproduced
that omission. Commit `70f60eb` introduces prompt identity
`m15-whole-scope-hierarchy-prompt-v3` and consent-bound repair policy
`m15-whole-scope-targeted-repair-v3`. The repair now requires evidence-based re-evaluation,
permits an empty uncertainty list only after confident placement, and explicitly requires truthful
uncertainty to remain so the run still fails closed. The focused correction tests passed 2/2; the
broader M15.1/product set passed 104/104; Ruff and strict mypy passed. The full repository run had
1,496 passes, five expected skips, and only the known hardware-sensitive M06 timing threshold at
2.035 seconds; that exact benchmark passed immediately in isolation at 1.86 seconds.

The corrected contract preserves every authority and privacy boundary, changes consent/cache
identity, and does not weaken uncertainty handling. The lifecycle therefore moved through
`Semantic review` and returns to `In progress` with a repeated semantic `PASS`, pending independent
exact-head review and a fresh zero-submit manifest.

The first exact-head review of `496350e` returned `FAIL` on lifecycle evidence only: the goal still
contained one stale per-manifest approval clause, the gate paragraph prematurely generalized a
predecessor review, and `COMPLETION_REPORT.md` presented superseded boundary/summary production as
current. It found the runtime correction sound. Those P1/P2 findings are corrected: the standing
authorization is now unambiguous without weakening exact manifest controls, predecessor and current
reviews are distinguished, and the completion report labels historical production explicitly.
Two additional reviewer-suggested regressions prove that an unlocked uncertain proposal may
legitimately regroup units and that repeated truthful uncertainty remains terminal. The expanded
M15.1/product set passes 106/106; the three uncertainty-specific tests pass; Ruff and strict mypy
remain clean. Independent rereview returned `PASS` at exact head
`e33b77384364ad37b9febbe5944a21aca8217af8` with no P0-P2. The full functional repository suite
then passed 1,498 tests with five expected opt-in skips and the known load-sensitive M06 benchmark
deselected; that benchmark passed separately at 1.97 seconds. Live zero-submit preparation may now
proceed from this reviewed correction.

## Gate decision

The observable done condition remains unchanged. The corrected Stage H projection now supplies the
semantic evidence and complete bounded structural context required by criterion 3, binds it to one
typed authority seam before durable state or consent, preserves valid retained items exactly during
repair, and proves every legal repair envelope remains below its sterile ceiling. Identity changes
invalidate the exhausted manifest and all older cache/consent paths. The implementation remains
subordinate to M10/M11 authority and provider text remains transient. Predecessor correction head
`a7997b1` passed independent review with no P0-P2; this prompt/policy correction independently
passed exact-head rereview at `e33b773` with no P0-P2.

The semantic gate is `PASS`. Manifest `consent_5181073c41933f07c2ccc887` is exhausted and cannot be
reused. Commit `70f60eb` changes the prompt and repair-policy identities, so the next Stage H run
requires a fresh zero-submit preparation and exact manifest audit. The user's standing
authorization permits the coordinator to execute that fresh bounded manifest without another
routine approval pause once exact identity, unchanged fingerprints, privacy, and limits are
verified and recorded. Stage E remains impossible until Stage H freezes and must still receive its
own fresh exact manifest under the same audit discipline.

PASS
