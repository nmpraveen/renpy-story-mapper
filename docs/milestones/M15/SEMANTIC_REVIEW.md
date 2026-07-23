# M15.1 semantic review

Date: 2026-07-23

Architectural correction base: `1c66cc3312e2af322f405c161df47a495cce617f`

Prior decision: 2026-07-21 `PASS`, revoked because it made adjacent-gap classification the primary
AI semantic task.

Decision: REVISE

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

This commit records the lifecycle transition and reconciled contract. Broad implementation remains
stopped until the coordinator repeats this gate against the complete revised contract and records
`PASS`.

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

## Resolved conflicts and remaining gate

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
- This resumption and historical consent do not authorize Stage H or Stage E provider transmission.

## Gate decision

The prior adjacent-gap-only semantic `PASS` is invalid. The revised authority split and contract are
now explicit, but this transition commit intentionally leaves the milestone in `Revise` while the
single semantic review is repeated against the reconciled documents. No broad product work may
begin from this decision.

REVISE
