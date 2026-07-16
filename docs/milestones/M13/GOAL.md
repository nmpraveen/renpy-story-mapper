# M13 - Optional AI narrative layer

Status: In progress (semantic review PASS)

Scope authority: `docs/MASTER_PLAN.md`, the approved planning proposal, the user's 2026-07-16
implementation approval, and its twelve binding amendment sections

Baseline: `f67df8a7cb805bf4adf8590585bae700d2f3117f`

Integration branch: `codex/m13-narrative-layer`

## Done condition

M13 is PR-ready when the local browser can optionally enrich an exact current M10/M11/M12-bound
project with independently durable, evidence-grounded scene titles and summaries; claim-level
partial salvage; deterministic bounded scene-to-segment-to-chapter/route/ending/plot reductions;
route-aware character interpretation; exact lazy evidence traversal; and a consented, cancellable,
budgeted cloud-provider workflow with deterministic batching and zero-call cache replay, while all
deterministic maps, scene membership, route results, source inputs, and provider-free behavior
remain unchanged and useful, required Windows and private acceptance passes, no unresolved P0 or
P1 finding remains, and one approval-gated M13 pull request is genuinely ready but not created or
merged without separate user approval.

## Objective

Add the optional AI narrative layer over M10 canonical facts/evidence, M11 human story records,
and current M12 route results. Produce concise human-readable titles, summaries, character
participation and bounded interpretations, hierarchical route-aware summaries, and optional weak
boundary review overlays without transferring deterministic authority to AI or requiring AI for
the existing map, scene view, evidence workspace, or route solver.

## Deliverables

- Versioned M13 contracts for logical jobs, input revisions, provider transport batches, consent,
  provider/model/settings identity, prompt-local evidence handles, claim DAGs, artifacts,
  coverage, attempts, budgets, contradictions, and lazy evidence resolution.
- Independent scene title/summary jobs with deterministic input projection, stable identity,
  exact M10/M11 binding, claim-level validation, at most one targeted repair, partial salvage,
  deterministic-title fallback, and job-local refusal/failure.
- A durable queue, exact cache, retry-only-failed workflow, cancellation, timeouts, transient
  retries, call/token/time/cost budgets, and deterministic multi-scene transport batching whose
  batch items commit independently.
- Deterministic non-user-facing summary segments with bounded child/token fan-in, structural and
  route-context safety, independent persistence, missing-child coverage, and recursive fan-in.
- Chapter, persistent-route, ending, route-aware whole-plot, and bounded character artifacts that
  preserve common story, temporary branches/rejoins, mutually exclusive persistent routes,
  route-specific development, endings, prerequisites, M12 statuses, unresolved behavior, and
  missing coverage.
- One approved cloud-provider adapter through the existing provider boundary plus
  provider-independent interfaces, versioned reviewable prompt templates, structured-input-only
  process isolation, and runtime requested/resolved model identity without hard-coded model or
  chat settings in repository contracts/tests. LM Studio remains optional.
- Simple manifest-bound cloud consent per selected run/scope, with fact-only/story-text mode,
  logical-job and estimated batched-call counts, estimated tokens/cost, budgets, selected scope,
  and M12-material disclosure.
- Project-local storage that reuses existing patterns and persists normalized input hashes,
  consent, provider identity, metrics, sanitized errors, validated claims/artifacts, bounded
  direct support, and job/attempt state, but not complete raw prompts, source packets, or raw
  provider responses by default.
- A browser Narrative toggle, evidence-linked scene and hierarchy summaries, coverage state,
  provider/job drawer, cancellation/resume/retry controls, and lazy claim-DAG citations within the
  existing two product levels.
- Provider-free complete-private-scale simulation and bounded consented live-provider acceptance,
  plus required Windows, browser, package, privacy, immutability, review, and milestone evidence.
- Optional weak-boundary suggestions only after the core hierarchy is complete; advanced
  character analysis, local-provider integration, and export polish cannot delay release-critical
  work.

## Acceptance criteria

1. Every logical job has a stable provider-independent ID and exact input revision; every cache
   entry additionally binds prompt/output schemas, provider adapter/version, requested and
   resolved model identity, settings, and normalized input. Stale or mismatched authority is never
   presented as current.
2. M13 consumes exact M10 source generation/schema/hash and referenced authority, exact M11
   schema/model/correction binding and story records, and current M12 request/result identities
   where relevant. M13 changes no M10, M11, or M12 authoritative bytes or memberships.
3. Independent scene jobs produce bounded title/summary and character-participation artifacts.
   Invalid AI titles retain the deterministic M11 title; unsupported interpretation never
   discards otherwise valid factual scene work.
4. Prompt-local evidence and child-claim handles are deterministically mapped by Python. Unknown,
   duplicate, malformed, or out-of-scope handles cannot be published. Every published factual
   scene claim has valid direct owned evidence.
5. Claims are validated and persisted independently. At most one targeted schema/claim repair is
   attempted; valid claims survive, invalid claims are omitted or marked, partial artifacts carry
   coverage warnings, and whole artifacts are rejected only when their binding, ownership, or
   core structure is unsafe.
6. The scheduler may deterministically batch small scene jobs within transport limits, but batch
   output is keyed by logical job ID, valid items commit independently, malformed items retry
   independently, unusable batches split deterministically, and no batch can merge scene ownership
   or invent cross-scene chronology.
7. Durable jobs, attempts, cache, consent, metrics, artifacts, and bounded support survive reopen,
   cancellation, refusal, partial failure, and restart. Retry failed never reruns validated/cache
   hits, and exact accepted-artifact cache replay makes zero provider calls.
8. Deterministic summary segments derive stable IDs from ordered child artifacts, structural
   context, partition version, locale, and perspective; respect M11 chapter, lane, temporary,
   occurrence, loop, and chronology boundaries; use approximately 16-32 children subject to token
   preflight; recurse through bounded fan-in; persist independently; and never masquerade as M11
   membership.
9. The claim DAG stores direct evidence only on scene claims and child claim IDs on ancestor
   claims. Detail/Evidence resolves transitive authority lazily with cycle/depth/size bounds, and
   scale acceptance proves approximately linear artifact and provenance growth.
10. Chapter, persistent-route, ending, plot, and character artifacts consume bounded segments or
    bounded child artifacts rather than unbounded scene sets or full-project text. The plot never
    consumes every raw scene artifact.
11. Route-aware outputs distinguish shared story, temporary branches/rejoins, each persistent
    route, route-specific character development, endings, known prerequisites, unresolved
    behavior, and missing coverage. Mutually exclusive routes are never rendered as one
    chronology.
12. M12 status and prerequisite wording are preserved exactly. M13 may summarize but never
    upgrade or reinterpret confirmed, prerequisite, best-known, incomplete, dynamic, conditional,
    infeasible, or negative conclusions.
13. Contradiction identity includes lane/route, temporal scene/chapter anchor, occurrence/call
    context, factual/interpretive class, subject, predicate, polarity, and normalized value.
    Mutually exclusive routes and legitimate temporal change do not false-positive; interpretive
    disagreements are review warnings only.
14. One working approved cloud provider uses the provider-independent boundary with explicit
    runtime provider/model/settings identity, no silent fallback, versioned prompt templates,
    structured input, cancellation, timeout, transient retry, call/token/time/cost controls, and
    no tools, web, MCP, filesystem, or application authority. No repository contract/test
    hard-codes a specific model, reasoning level, or chat-session setting.
15. Cloud AI is disabled by default. One exact manifest-bound consent per selected run/scope shows
    provider/model, selected scope, fact-only/story-text mode, logical-job count, estimated batched
    calls, estimated tokens/cost when reliable, hard limits, and M12 inclusion; after consent, work
    continues until a terminal state without per-job prompts.
16. Production storage does not retain complete raw prompts, source-text packets, or raw provider
    responses by default. Raw debug retention requires an explicit development-only option that is
    off by default; credentials, absolute paths, and unsanitized provider errors are never stored.
17. The browser keeps the deterministic M11 map as a useful provider-free surface, adds an
    optional Narrative toggle and compact coverage/job controls, exposes factual versus
    interpretive labels, and resolves citations through existing Detail/Evidence without adding a
    third semantic level or invoking a provider on open/navigation/replay.
18. Weak-boundary suggestions, if delivered, are separately persisted review overlays limited to
    safe weak M11 candidates and never auto-apply or alter M11. Their absence does not block M13
    completion.
19. Provider-free acceptance simulates the complete current private-corpus scale, including all
    scenes, batching, hierarchy reduction, retries, partial jobs, cancellation, invalidation,
    exact cache replay, route separation, and approximately linear storage/provenance growth.
20. Bounded live-provider acceptance covers common spine, temporary branch, persistent route,
    shared occurrence, loop/repeatable context, M12 prerequisite, ending, and one complete
    route-aware plot reduction under exact consent. Cached artifacts/rendering reproduce exactly;
    regenerated provider prose is not required to be byte-identical.
21. Source/archive fingerprint, M10 canonical hash, M11 model/membership hash, and M12 normalized
    result bytes remain unchanged. No Ren'Py, game, creator Python, runtime tracing, implicit
    provider request, or unauthorized remote action occurs.
22. Windows CPython 3.12 focused/full pytest, Ruff, strict mypy, `pip check`, JavaScript checks,
    migration/fault/scale/browser/privacy/package acceptance, and an independent review complete
    with no unresolved P0 or P1 finding. P2 findings may be documented and deferred.
23. Required milestone reports, exact commands/results, private evidence, limitations, validated
    integration commit, and native infographic are durable; one M13 PR is ready but is neither
    created nor merged without explicit user approval.

## Required evidence

| Criterion | Evidence required | Result / durable location |
|---|---|---|
| 1-5 | Contract/handle/claim validation tests, normalized hashes, partial-salvage cases | Pass; `VALIDATION_REPORT.md`, product head `859328e` |
| 6-9 | Batching, retry, persistence, cancellation, segment, DAG, lazy-resolution, scale tests | Pass; focused/full suites and private-scale report in `VALIDATION_REPORT.md` |
| 10-13 | Hierarchy, route separation, M12 preservation, contradiction-context fixtures | Pass; focused/full suites and primary adversarial corrections in `859328e` |
| 14-16 | Provider/process, prompt-template, consent, budget, storage/privacy tests | Pass in mocked/provider-free acceptance; bounded live submission awaits exact manifest consent |
| 17-18 | API/real-browser narrative and optional overlay evidence at 100%/200% | Pass; browser report SHA-256 `2b938d37b152456cf3646f23ebda98d73ccc79c79379394ec35aa4df01a88273`; optional weak-boundary overlay deferred |
| 19-21 | Provider-free full-private simulation, bounded live/private acceptance, fingerprints/hashes | Provider-free/private pass; live criterion 20 pending exact consent; details and hashes in `VALIDATION_REPORT.md` |
| 22 | Focused/full Windows suite, package inspection, independent review | Suites/package pass; separately configured independent review pending |
| 23 | Reports, integration commit, infographic, PR state | In progress; reports/product head durable, infographic/final review/live evidence pending, no PR created |

## Release-critical sequence

1. Contracts and evidence-handle protocol.
2. Independent scene title/summary jobs.
3. Claim-level validation and partial salvage.
4. Durable queue, cache, retry, cancellation, and batching.
5. Deterministic segment reduction hierarchy.
6. Chapter, route, ending, and route-aware plot summaries.
7. Browser Narrative toggle, citations, coverage, and job drawer.
8. Privacy and budget acceptance.
9. Bounded character roles and interpretations.
10. Optional weak-boundary suggestions.
11. Optional local-provider adapter and export formatting.

## Exclusions

- No changes to M10 nodes, edges, conditions, effects, reachability, regions, merges, loops,
  terminals, authority hashes, or canonical inspection.
- No route correctness decision, M12 route modification, automatic destination solving,
  playthrough enumeration, arbitrary satisfiability, or status upgrade.
- No silent M11 scene/chapter/lane/temporary-container/occurrence/loop membership change and no AI
  chronology or ownership authority.
- No Ren'Py, game, creator Python, screen, application, runtime tracing, or M14 work.
- No global prompt, full-story raw-text request, unbounded fan-in, all-or-nothing stitch, hosted
  service, chatbot/Q&A, automatic game control, walkthrough dependency, media analysis, model
  training, installer, or public distribution.
- No mandatory LM Studio/local-provider adapter, weak-boundary delivery, advanced character
  analysis, or export polish when those would delay the core narrative hierarchy.
- No complete raw-prompt/source-packet/raw-response retention by default and no credential or
  absolute-path storage/transmission.
- No M13 pull request creation or merge without explicit user approval.

## Handoff rules

- Provide the exact commit, branch or worktree, changed files, validation commands/results,
  assumptions, known defects, likely conflicts, and remaining acceptance work.
- Worker tasks must use the literal assigned base, stay inside their owned files and exclusions,
  run named checks, and must not create pull requests.
- Follow the repository's external dispatch policy where controls expose its settings. Current
  collaboration controls do not expose model/reasoning/fast-mode selectors; record that
  limitation rather than copying fixed provider settings into this M13 contract or claiming an
  unverifiable configuration.
- Keep status at `Integration` until worker changes are integrated and reviewed.
- Keep the native Codex goal active through integration, verification, evidence, review, and PR
  preparation. Complete it only at genuine `PR ready`.
