# M13 semantic review

Date: 2026-07-16

Baseline: `f67df8a7cb805bf4adf8590585bae700d2f3117f`

Contract: [`GOAL.md`](GOAL.md)

## Decision

The approved M13 contract is semantically complete and implementable after one contract-text
correction made during this review: the M13 handoff text no longer repeats fixed dispatcher model
or reasoning values. The project-wide dispatch policy remains an external orchestration rule, but
M13 product contracts and tests will contain no fixed provider model, reasoning level, or chat
setting. Runtime requested and resolved provider identities remain explicit.

## Authority and ownership audit

| Area | Deterministic owner | M13 may consume or add | M13 must never do | Decision |
|---|---|---|---|---|
| Graph facts and evidence | M10 canonical graph | Exact current facts, evidence, provenance, hashes, and bounded story text when consented | Change graph records, reachability, regions, loops, merges, terminals, conditions, or effects | PASS |
| Human story structure | M11 scene model and corrections | Scenes, chapters, lanes, temporary containers, occurrences, loops, chronology, titles, memberships, and provenance | Change membership or present M13 segments as M11 structure | PASS |
| Routes and prerequisites | M12 requests and normalized results | Exact status and prerequisite text, result identity, bounded route context, and explanations | Decide correctness, modify routes, upgrade status, or flatten exclusive arms | PASS |
| Narrative artifacts | M13 | Titles, summaries, roles, labeled interpretations, route-aware hierarchy, coverage, suggestions, and citations | Become deterministic authority or make provider use mandatory | PASS |
| Provider execution | M13 provider boundary | Transmit one consented structured, bounded request and accept schema-bound output | Give tools, web, MCP, filesystem, application, game, or runtime authority | PASS |

## Binding-amendment audit

| Amendment | Contract coverage | Implementable invariant |
|---|---|---|
| Deterministic summary segments | Criteria 8-10 | Partition ordered children inside structural/route context; token preflight; bounded recursive fan-in; independent rows and coverage |
| Logical jobs versus transport batches | Criteria 1, 6, 7 | Logical identity/state never depends on packing; keyed items validate and commit independently; unusable batches split deterministically |
| Claim DAG and evidence handles | Criteria 4, 9 | Python owns handle tables; scenes point to direct evidence and ancestors point to child claims; bounded lazy traversal rejects invalid references |
| Context-aware contradictions | Criterion 13 | Identity includes route/lane, temporal and occurrence anchors, claim class, subject, predicate, polarity, and normalized value |
| Claim-level salvage | Criteria 3-5 | One targeted repair at most; validate each claim; publish safe partial artifacts and deterministic-title fallback |
| Narrow v1 provider | Criterion 14 | One cloud adapter, provider-neutral protocol, explicit requested/resolved identity, no fallback, runtime limits, isolated process |
| Simple cloud consent | Criterion 15 | One exact manifest per selected run/scope; no per-job prompts; estimates, disclosure, and hard limits bound before start |
| Route-aware narrative | Criteria 10-13 | Shared, temporary, persistent, ending, prerequisite, unresolved, and missing-coverage sections remain distinct |
| Release priority | Release-critical sequence | Optional boundary, advanced character, local provider, and export work cannot block the core hierarchy |
| Acceptance | Criteria 19-23 | Complete provider-free scale simulation plus bounded consented live sample and immutable-authority hashes |
| Storage and privacy | Criteria 7, 16, 21 | Persist hashes, consent, identities, metrics, sanitized state, claims, artifacts, and bounded support; raw payload debug is explicit and off |
| Implementation process | Handoff rules and exclusions | One branch, one goal, one semantic gate, no PR without approval, no M14 |

## Architecture decision

M13 will be a new `renpy_story_mapper.narrative` package. It will use immutable mappings and
canonical JSON at public and persistence boundaries. Deterministic projection, identity,
validation, partitioning, persistence, and rendering remain provider-free.

1. `contracts.py` defines versioned logical jobs, authority/input revisions, provider and settings
   identities, consent manifests, attempts, claims, artifacts, coverage, and limits. No model,
   reasoning level, or chat-session value is a repository constant.
2. `evidence.py` creates deterministic prompt-local handle tables from in-scope authority,
   validates direct and child-claim references, and resolves the claim DAG lazily with cycle,
   depth, and result bounds.
3. `projection.py` reads current M10/M11/M12 payloads and constructs bounded scene and hierarchy
   inputs without executing source or changing authority.
4. `validation.py` validates each provider item and claim independently, permits at most one
   targeted repair through the scheduler, salvages safe partial artifacts, and performs
   context-aware contradiction checks.
5. `batching.py` deterministically packs logical scene jobs into transport requests and splits an
   unusable request without changing logical identity or discarding prior artifacts.
6. `segments.py` deterministically partitions ordered child artifacts inside chapter, lane,
   temporary-container, occurrence, loop, chronology, locale, and perspective context. It creates
   a bounded fan-in tree and never creates or mutates M11 membership.
7. `persistence.py` stores independently keyed run, consent, job, attempt, cache, claim, artifact,
   and segment envelopes using the existing atomic payload mechanism. New payload collections do
   not require a SQLite schema migration because the generic payload table already owns canonical
   hashing and transactional publication.
8. `scheduler.py` serializes durable state mutation around bounded concurrent provider calls;
   enforces call, input/output token, elapsed-time, cost, and concurrency limits; observes
   cancellation; retries only eligible failed items; and replays exact accepted cache hits with
   zero provider calls.
9. `provider.py` defines provider-independent interfaces and one approved cloud adapter. The
   adapter reuses or extracts the existing direct-process isolation mechanics while leaving legacy
   M05/M07 behavior compatible. Local Python reads versioned repository prompt templates and sends
   rendered structured input over stdin; the provider process receives no ambient authority and
   no silent model fallback.
10. `service.py` prepares exact run manifests, estimates transport, consumes one consent, drives
    scene-to-segment-to-hierarchy work, and serves current artifacts only when authority bindings
    match.
11. The existing local API and two-level browser add a Narrative toggle, coverage and job drawer,
    run/cancel/retry controls, labeled fact/interpretation content, and lazy Detail/Evidence
    citations. Open, navigation, cache replay, and disabling Narrative make no provider call.

The first implementation slices may keep tightly coupled functions in fewer modules, but these
boundaries and the one-way authority flow are contractual.

## Identity and boundedness decisions

- A logical job ID hashes job kind, owned structural context, ordered child authority or artifact
  IDs, locale, perspective, and contract/partition version. Its input revision separately binds
  current M10/M11/M12 identities and normalized bounded input.
- A cache key additionally binds prompt/response schema versions, provider adapter/version,
  requested and resolved model identity, settings, and normalized input hash. A different resolved
  identity cannot reuse or overwrite another cache entry.
- Transport batch identity is operational and does not enter logical job identity. Output items
  must carry exactly one known logical job ID; missing, duplicate, foreign, or cross-owned items
  are invalid.
- Initial segment target fan-in is 24 children, inside the approved approximate range of 16-32,
  with token preflight allowed to reduce effective fan-in. Oversized results form another
  deterministic reduction level.
- Higher artifacts cite child claim IDs only. Direct M10 evidence is stored once at scene-claim
  leaves; bounded support and lazy traversal prevent transitive duplication.
- Plot construction receives bounded chapter, route, ending, and segment artifacts selected by a
  deterministic route-aware plan. It never receives all raw scenes or full-project text.

## Persistence and privacy decision

The generic payload table is sufficient for v1 because it offers canonical JSON, record-level
keys, hashes, atomic transactions, and exact enumeration. M13 will register dedicated collection
names for durable logical state. Raw prompts, source packets, and provider responses are absent
from production envelopes. Any raw debug retention is explicit, development-only, bounded, and
off by default. Stored errors are allowlisted and sanitized; consent binds hashes rather than
copied source text.

## Provider-boundary compatibility decision

The existing organization provider has useful direct-process isolation and cancellation, but its
public contract intentionally hard-codes the legacy M05/M07 model and organization schema. M13
will not reuse that semantic contract. It will add a generic structured-provider runner beneath or
beside the legacy wrapper and keep existing behavior unchanged. M13 records requested and resolved
identity at runtime and rejects mismatch instead of falling back. LM Studio is optional.

## Expected change surface

- New package: `src/renpy_story_mapper/narrative/` plus versioned prompt and response-schema
  resources.
- Integration: payload collection registration, project service factory, API contracts/routes,
  API lifecycle wiring, and existing static browser assets.
- Tests: contracts/identity, handle ownership, claim salvage, contradictions, batching,
  persistence/reopen, cancellation/retry/budgets, segmentation/fan-in, hierarchy/route separation,
  provider isolation, consent/privacy, service/API, rendering, and exact cache replay.
- Acceptance: provider-free complete-private-scale simulator, bounded consented live/private
  runner, real-browser run at 100% and 200%, immutability/fault checks, and package inspection.
- Evidence: `VALIDATION_REPORT.md`, `COMPLETION_REPORT.md`, review findings, browser/private artifact
  references, and `INFOGRAPHIC.png` after verification.

## Acceptance-evidence map

| Criteria | Primary evidence |
|---|---|
| 1-5 | Canonical identity, handle, ownership, per-claim validation, repair, and salvage tests |
| 6-9 | Batching/split, durable retry/cancel/reopen, segment tree, lazy DAG, and scale-growth tests |
| 10-13 | Route-aware hierarchy fixtures, exact M12 wording, and temporal/route contradiction cases |
| 14-16 | Fake process/provider tests, bounded live sample, identity-mismatch refusal, consent, budgets, and database privacy inspection |
| 17-18 | API integration and real-browser behavior at normal and 200% zoom; optional overlay tests only if shipped |
| 19-21 | Full private-shape provider-free simulation, bounded live/private matrix, cache call counter, and before/after source/M10/M11/M12 hashes |
| 22-23 | Windows quality gates, package checks, independent severity review, milestone reports, exact integration commit, infographic, absent PR |

## Risks and controls

- Durable run state, not the browser's single background task, is authoritative; restart and
  cancellation cannot erase validated work.
- Token and price estimates can be unreliable. Consent distinguishes known, estimated, and
  unavailable cost data while call/token/time ceilings remain enforceable.
- Missing private source or live-provider access blocks only its acceptance evidence, not
  provider-free implementation or tests.
- Collaboration controls used for read-only surveys exposed no model/reasoning/fast-mode selector.
  The project-required dispatch configuration could not be verified and is recorded as an
  orchestration limitation, never product behavior.

## Semantic result

PASS

The corrected contract has one observable outcome, exact authority boundaries, bounded reduction
and provenance designs, privacy and failure semantics, ordered implementation slices, and
executable acceptance evidence. No further planning round or scope revision is required.

## Post-merge cumulative-resource correction gate - 2026-07-17

PASS

The user-authorized correction retains M13's done condition and exclusions. Static inspection at
merged baseline `d37fe236d576eea553fb7aef9ecc2c5b6c2e0c5a` confirms that
`NarrativeScheduler.run()` combines durable current-phase usage with supplied prior cumulative
usage through component-wise maximums. Those histories can be disjoint, so calls, tokens,
elapsed time, and known cost can be understated before hard-limit admission. Peak concurrency is
the exception and remains a maximum.

The architecture boundary is limited to scheduler/workflow/pipeline cumulative-usage provenance
and directly focused tests. Track A alone may write product code. Before implementation, its
failing-first regression and proposed provenance/separation model must pass a shared Track B
semantic/invariant review. The model must add disjoint usage once, de-duplicate overlap and
compatible finished records, preserve reservation/attempt correspondence and legacy behavior,
and fail closed for unknown cost. M10-M12 authority, consent/privacy identity, cache/replay,
browser behavior, provider execution, broad refactoring, PR merge, and M14 are outside the change
surface. The correction criteria map to failing-first focused tests, two read-only design/code
reviews, an exact-diff final review, integrated focused checks, one Windows Release, lifecycle
schema/docs checks, and exact-head PR CI.
