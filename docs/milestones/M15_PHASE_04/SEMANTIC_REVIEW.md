# M15.1 Phase 04 semantic review

Date: 2026-07-26

Baseline: exact contract checkpoint `2a7f728f2de2af78adee059b1cd95136eea8668e` for
`codex/m15-phase04-full-game`; the independent review worktree was detached at that exact commit
because the branch was checked out in the coordinator worktree.

Decision: REVISE

## Requirements

| Requirement / exclusion | Authority and repository seam | Verified interpretation | Result |
|---|---|---|---|
| 1. M11-first occurrence-aware placement | `MASTER_PLAN.md` M15; approved design; `m11_scene_model.py` chapters, lanes, scenes, occurrences, and loop hubs; `story_map_v2/source_adapter.py` | A new frozen Story Plan must order by M11 chapter/lane/scene/call occurrence before relative path and line. Shared callee content needs one placement per narrative occurrence; persistent lanes remain child scopes; repeatable content is represented once with explicit loop metadata. The current adapter uses M11 only as an optional hint and orders path/line before its rank, so changing this seam is required and authorized. | Yes |
| 2. M10 mechanics and M12 witness authority | Master-plan non-negotiables; `canonical_graph_contract.py`; `m12_model.py`, `m12_service.py`; V2 overlay/navigation | Exact captions, arm order, predicates, effects, destinations, proven rejoins, reachability, warnings, terminals, and evidence remain M10-derived. M12 alone supplies route-to-target witnesses. Provider outputs may reference supplied IDs but cannot create or change these facts. | Yes |
| 3. Frozen Story Plan and chunk plan | Approved design; current `StoryScope`/`StoryChunk` contracts and generic payload transaction seam | Persist canonical plan records, ordered placements, rendered-input/mechanics identities, and chunk membership before execution. Resume and assembly must consume those exact records; no source re-adaptation or chunk replanning is permitted during assembly. | Yes |
| 4. 8k/5k targets and 10,700 hard ceiling | Approved Phase 01/04 sizing; current `ChunkProfile`, `planner.py`, `mapper_io.py` | About 8,000 and 5,000 are raw-story targets. The 10,700 hard limit applies to the complete serialized provider request under one versioned conservative token-counting contract, not merely `StoryChunk.raw_tokens`. Oversized routes/choices may split only at deterministic arm/scene boundaries, repeat compact parent mechanics, retain one Python-owned parent, and prove exactly-once placement coverage. The current planner intentionally rejects oversized indivisible choices, so replacement behavior is in scope. | Yes |
| 5. Zero-submit Prepare | Approved design; current `prepare_preview()` defers construction but has Phase 02 ceilings | Prepare must be deterministic and provider-free, and its frozen preview must bind authority, exact plan/request identities, cache-hit/pending work, Terra/High/fast-off, six slots, cloud/local disclosure, and finite mapping/review/rollup/fallback ceilings. Provider factories must be trapped in focused tests. | Yes |
| 6. Exact approval, resume, and indeterminate retry | Approved design and criterion 6 | One approval covers the unchanged frozen run and all ordinary resume work. Authority, plan, transmitted request bytes, prompt/schema/adapter, provider/model/settings, or ceilings changing invalidates it. An indeterminate attempt is the only retry case requiring a new job-specific approval. | Yes |
| 7. Six independent durable workers | Approved design; current V2 executor is sequential and non-durable | The Phase 04 V2-native scheduler may have at most six submitting claims globally across processes. Each job maps to one independent request; no batching, adaptive ramp, recursive provider split, automatic retry tree, or reused attempt ordinal is allowed. Durable reservation and lease/CAS state precede possible transmission. | Yes |
| 8. Validation, one review, refusal-only loopback | Approved design; V2 mapper validation/overlay and transports | Python validates all results. Only a flagged cloud result may receive one Terra replacement-review call. A content refusal may receive one configured Qwen loopback mapping call only when that contingency was explicitly disclosed and approved in the unchanged frozen preview. Invalid local output falls back structurally and never returns to cloud. The baseline contract instead said “separately approved,” contradicting the locked one-approval policy; `GOAL.md` is corrected in this review. | Revised |
| 9. Provider prose never owns mechanics | Master-plan rules 3, 4, and 8; `overlay.py`, `assembly.py` | Every fresh or cached response is validated against and overlaid with current plan authority immediately before immutable publication. Provider-supplied mechanics are rejected or ignored, never trusted. | Yes |
| 10. Cancellation, reopen, and uncertain transmission | Approved design; current project open/read and transport cancellation seams | Cancellation state commits before transport signalling, prevents new claims, and retains completed immutable work. Open/status/read construct no provider. A crash after durable submission reservation but before definite non-transmission becomes `indeterminate` and cannot auto-resubmit. | Yes |
| 11. Exact cache identity and privacy | Approved design; generic canonical payload hashing; existing V2 request serializers | Cache identity binds exact transmitted request bytes plus prompt/schema/adapter, provider, requested/resolved fixed model identity, reasoning, fast mode, and cloud/local mode, while excluding run/lease routing. Production storage excludes source packets, rendered prompts, credentials, provider stderr, absolute private paths, and unsanitized errors. | Yes |
| 12. Structural-first progressive immutable publication | Master-plan deterministic fallback rule; approved design; current single `story_map_v2/current` envelope | A structural generation and predetermined slots publish immediately. Candidate scopes fill immutable slots as jobs finish. Updated projects keep the prior complete pointer while building; corrupt/failed candidates cannot replace it; final publication advances one complete pointer atomically. | Yes |
| 13. Python-proven meaningful sections and rollups | Approved design; current one-call Phase 03 synthesis is read-only compatibility, not the Phase 04 implementation | Terra returns prose and existing event-range references only. Python proves ordered, contiguous, exactly-once corridor coverage and route ownership. Fixed-membership consecutive reduction handles large rollups. Invalid sectioning/rollup uses deterministic child summaries without semantic repair. | Yes |
| 14. Small complete manifest and lazy bounded reads | Approved design; current V2 API returns one monolithic page and browser validator caps 64 sections/512 events | The new manifest contains every section descriptor and landmark but no hydrated full map. Section, branch, search, locate, path, detail, and view-state reads are independently bounded and indexed. No endpoint may rebuild or serialize the complete monolithic map for ordinary navigation. | Yes |
| 15. Revision-bound opaque cursors | Approved design; current V2 API has no map revision/cursor contract | Every response carries one generation/map revision. Server-minted opaque cursors bind revision, collection identity, stable order, offset, and limits; malformed/tampered cursors fail closed and stale revision use returns typed HTTP `409 stale_map_revision`. | Yes |
| 16. Accepted two-level vertical browser | Master plan two-level map; accepted Phase 03 V2 browser; approved design | Preserve normal-flow semantic HTML, local nested choices, persistent lanes, rejoins, selection/focus, Path, Detail/Evidence, and exact return state. Hydrate a bounded section/window with at most one prefetched neighbor and 600 live story items. Validate desktop 100%, effective 200%, and narrow width with minimal helper copy and local assets only. | Yes |
| 17. Stale preservation and deterministic `NEW` | Approved design | Refresh preserves the prior accepted generation as stale. Compare only deterministic new arm/route/ending facts against the immediately prior accepted generation; label affected sections until the following source generation. Provider wording changes cannot create `NEW`; hiding labels is presentation-only. | Yes |
| 18. Compatibility and schema-v7 migration | Approved design; `storage.py` is schema v6; `Project.open()` already creates a verified pre-migration backup; Phase 03 V2 uses the generic current envelope | Existing Phase 03 records remain readable but immutable. Opening schema v6 for migration must create and verify a backup before schema v7 writes. Phase 04 may add indexed V2 tables/services, but cannot import or schedule through rejected Stage H/E/M13 semantics. | Yes |
| 19. Deterministic scale fixture | Approved criterion 19; existing M10/M11/M12 scale harness pattern | A public synthetic fixture must meet every stated minimum simultaneously and report plan/coverage hashes, API latency/bytes, browser DOM, memory, and repeated navigation. The final-section, cross-section-rejoin, oversized-branch, depth-eight, and 50-section-route cases must be asserted, not inferred from aggregate counts. | Yes |
| 20. Complete private MsDenvers run | Approved criterion 20; private artifacts remain outside Git | The supported website must complete the current private project with exact structural count/hash coverage. Any placeholders must be noncritical, at most two chunks and at most 5% of raw story tokens, and must exclude every choice/route/rejoin/ending/new-branch placement. A sanitized summary records only counts, hashes, thresholds, and status. | Yes |
| 21. Protected inputs, non-execution, and containment | Master-plan safety rules and exclusions | Record SHA-256, size, and timestamp before/after; do not execute game, Ren'Py, screen, or creator code; keep packets, responses, screenshots, private paths, and private derived prose outside Git; scan tracked changes and durable DB fields. | Yes |
| 22. Exact-head review, visual approval, quality, CI, and PR | Repository workflow; approved criterion 22 | Each track and the integrated candidate require exact-head review with no P0-P2. Focused/regression/scale/private/browser/static/quality/package gates must be attached to their exact heads. User approval covers exact-head 100%/200%/narrow screenshots. One Phase 04 PR remains open and unmerged at readiness. | Yes |
| Exclusion: no rejected semantic pipeline | Master plan M15 and Phase 04 exclusions; existing `organization/` and `narrative/` packages | No Stage H/E, adjacent-gap voting, atoms/claims, semantic locks, hierarchy repair, exact replay, or M13 scheduler dependency. Add an import/dependency gate proving the Phase 04 package does not use them. | Yes |
| Exclusion: no AI topology authority | Master-plan non-negotiables; M10/M12 contracts | No provider record can own or mutate choices, routes, rejoins, requirements, effects, reachability, endings, path witnesses, or evidence. | Yes |
| Exclusion: no new semantic/UI level | Master plan two-level map; approved browser design | No world canvas, generic technical graph redesign, route-map replacement, or third semantic level. Indexed sections are partitions within Level 1, not another navigation level. | Yes |
| Exclusion: no future/runtime scope | Master plan M14/M15; Phase 04 exclusions | No M14 tracing, game execution, creator execution, installer, legacy-workflow retirement, Phase 05 closure, or future-milestone acceptance. Python wheel/package validation is evidence, not installer scope. | Yes |
| Exclusion: no implicit provider work | Master-plan privacy rule 9; approved design | Import/open/read/status/stale detection/refresh never construct a provider or submit. Refresh may invalidate/stop work only. | Yes |
| Exclusion: no private material in Git | Master-plan repository rules; Phase 04 exclusions | No private source, prompt/response, screenshots, machine-specific canonical path, or private prose. Public synthetic fixtures and sanitized numeric/hash reports only. | Yes |
| Exclusion: do not merge | Approved handoff and criterion 22 | The coordinator may prepare/open the single PR but must leave it unmerged under this contract. | Yes |

## Architecture boundaries

- Authority and invariants:
  - M10 `CanonicalGraph` remains the sole owner of static topology, mechanics, reachability,
    terminals, evidence, and authority hash. Its schemas and builder semantics are inputs, not a
    Phase 04 change surface.
  - M11 `SceneModel` remains the sole owner of chapters, scene membership, persistent lanes,
    temporary containers, call-site occurrences, and loop repeatability. Phase 04 may create
    occurrence-specific placements that reference these records; it may not rewrite them.
  - M12 `RouteRequest`/`RouteResult` remain the path-witness authority. Phase 04 stores stable
    locator bindings and may cache/read current witnesses, but cannot modify solver semantics or
    upgrade incomplete/unresolved results.
  - Phase 04 owns the frozen `StoryPlan`, `StoryChunkPlan`, execution attempts/cache, immutable
    generations, section membership, locators, deterministic generation diff, and view state.
    Provider records own prose only.
- Actual seams that establish implementability:
  - `story_map_v2/source_adapter.py` already validates exact M10/M11 binding and extracts M10
    choice mechanics, but its current `(path, line, ..., M11 rank)` ordering is insufficient for
    criterion 1. It must be replaced/extended by an occurrence-aware planner rather than treated
    as accepted full-game order.
  - `story_map_v2/planner.py` already has coherent 8k/5k targets and a 10,700 raw estimate, but it
    rejects oversized spans/choice clusters and does not bind complete transmitted request size.
  - `provider_policy.py` is a Phase 02 sequential, six-total-call executor. Phase 04 needs a new
    durable six-concurrent-job service and must not silently reinterpret the old ceiling.
  - `story_map_v2/persistence.py` stores one `story_map_v2/current` blob. It is the read-only
    Phase 03 compatibility adapter, not the new indexed generation store.
  - `storage.py` is schema v6 and `Project.open()` already performs a pre-migration backup. Schema
    v7 can extend that verified lifecycle with indexed V2 tables and transactional pointers.
  - `web/contracts.py`/`web/api.py` expose monolithic map/path/detail V2 endpoints, and static
    `contract.js` caps the old payload. Phase 04 adds revisioned manifest/page/branch/search/locate
    and workflow endpoints while preserving read-only old-record projection.
- Components allowed to change:
  - New or versioned components under `src/renpy_story_mapper/story_map_v2/` for plan/placement,
    chunking, request identity, durable workflow, validation/review, generation assembly,
    sectioning/rollups, locator indexes, cursors, and deterministic diffs.
  - Existing V2 source-adapter/planner/mapper/overlay/assembly/persistence/presentation/navigation
    seams only where needed for versioned Phase 04 behavior and Phase 03 compatibility.
  - `storage.py`, `project.py`, and narrowly scoped project-analysis integration for schema v7,
    backup verification, V2 services, refresh invalidation, and atomic publication.
  - `web/contracts.py`, `web/api.py`, local server error mapping if required, and packaged static
    `index.html`, `app.js`, `api.js`, `contract.js`, `styles.css`, API documentation, and asset
    manifest.
  - Public synthetic fixtures, focused tests, acceptance scripts, and milestone evidence/docs.
- Components that must not change semantically:
  - M10 canonical graph construction/contracts, M11 scene construction/contracts/corrections, M12
    solving/cache semantics, ingestion/parser/source precedence, recovery isolation, and source
    evidence qualification.
  - Rejected `organization/` and `narrative/` semantic workflows, historical Stage H/E contracts,
    and M13 scheduler/pipeline behavior.
  - Existing Phase 03 stored bytes; compatibility is read-only. Protected source/archive/project
    inputs and private acceptance material must not be modified or committed.
- External, privacy, safety, and Windows boundaries:
  - Windows CPython 3.12 and the loopback-only website are runtime authority. Static browser assets
    are packaged locally; no remote asset, telemetry, hosted service, or browser-side filesystem
    authority is added.
  - Provider processes receive only an exactly approved bounded request through the existing
    sterile transport pattern: no shell, tools, web, MCP, repository, game, or ambient filesystem
    authority. Credentials remain managed by the provider boundary and are never read or copied.
  - This review made no provider call and did not open, parse, fingerprint, or transmit any private
    story source, private fixture, provider response, or screenshot.

## Expected files and tests

| Area | Expected files / components | Focused and regression checks |
|---|---|---|
| Story authority and plan | Versioned V2 plan/placement contracts; `source_adapter.py`, `planner.py`, `contracts.py` or new neighboring modules | M11 chapter/lane/scene/occurrence order, shared-callee occurrences, persistent child scopes, loops, nested/local/persistent choices, exact placement/coverage hashes, reordered source definitions |
| Packet planning and mapper boundary | V2 planner, `mapper_io.py`, schemas, cloud/loopback transport adapters | 8k/5k targeting, complete-request 10,700 ceiling, oversized arm/route splits, exact request bytes, schema/identity mismatch, no omitted/duplicated placement |
| Durable execution and cache | New V2 workflow/run/job/attempt/cache service; schema-v7 storage/project integration | zero-submit prepare, consent invalidation, six-slot barrier, multi-process claim/lease, attempt reservation, crash matrix, cancellation order, indeterminate recovery, cache mutation matrix, zero-call reopen |
| Validation/review/fallback | `overlay.py`, `assembly.py`, new review/fallback coordinator | foreign/missing/reordered/range-invalid output, mechanics overwrite attempts, one flagged Terra review, refusal-only preview-approved loopback, invalid-local structural fallback, no repair loop |
| Generations, sections, and diff | New immutable generation/publication/sectioning/rollup/diff components; Phase 03 compatibility adapter | structural-first publication, predetermined slots, corrupt candidate retention, atomic pointer crash, exact contiguous membership, fixed reduction, deterministic fallback, stale preservation, fact-only `NEW` |
| Indexed API and cursor security | `web/contracts.py`, `web/api.py`, V2 query/index components, optional `server.py` typed error mapping | manifest completeness, section/branch/search/locate/path/detail bounds, opaque cursor tamper, cross-identity reuse, stale typed 409, no monolithic rebuild, read paths provider-free |
| Browser and view state | Packaged `web/static/` files and asset manifest | lazy hydration/prefetch, 600-item DOM cap, persistent lanes/local choices/rejoins, search/locate unloaded content, path/detail return state, stale/NEW UI, 100%/200%/narrow Chrome, keyboard/focus, no remote requests |
| Migration and compatibility | `storage.py`, `project.py`, V2 persistence adapters | v6-to-v7 verified backup, injected migration failure/restore, Phase 03 old-record read-only reopen, current v7 reopen, corruption, refresh invalidation, no Stage H/E/M13 imports |
| Scale and acceptance | New public Phase 04 scale fixture/tests and acceptance scripts following M10-M13 harness conventions | exact criterion-19 counts/shape, API bytes/latency, DOM/memory/repeated navigation, provider-free fault matrix, sanitized private full-game run, protected fingerprints |
| Repository gates | `scripts/validate.ps1`, workflow contract, package resources, CI | focused/regression pytest, Ruff, strict mypy, `pip check`, JS syntax, JSON/schema/asset validation, `git diff --check`, Release wheel/sdist build-install-import, exact pushed-head CI |

## Acceptance evidence plan

| Criterion | Proof required | Command or durable artifact |
|---|---|---|
| 1 | Exact occurrence/lane/scene order, distinct shared-call placements, bounded loops | Focused public authority/plan tests plus normalized Story Plan and coverage hashes |
| 2 | M10 mechanics unchanged; M12 witnesses exact; provider topology mutations rejected | M10/M12 regression suites, overlay adversarial tests, before/after authority hashes |
| 3 | Same persisted plan/chunks used after close/reopen/resume/assembly | Persistence/reopen tests with byte hashes and a replanning trap that must remain uncalled |
| 4 | All complete request packets under ceiling with exactly-once placement across oversized cases | Chunk/serializer boundary tests and a packet metrics report containing raw/complete estimates and coverage hashes |
| 5 | Prepare creates no provider/call and freezes every disclosed identity/ceiling | Provider-factory trap tests and serialized zero-submit preview report |
| 6 | Exact approval replay, mutation invalidation, resume, and job-specific indeterminate approval | Consent identity matrix and durable recovery tests |
| 7 | Maximum six submitting calls across processes; no duplicate/batch/ramp/retry/ordinal reuse | Barrier/fault-injection/dual-process lease report with attempt ledger |
| 8 | Validation, one eligible Terra review, and only preview-approved refusal fallback | Fake-provider response matrix and exact call ledger for cloud/review/loopback paths |
| 9 | Current authority revalidation/overlay for accepted and cached prose | Cache-replay authority mutation tests and published-generation inspection |
| 10 | Persist-before-signal cancellation; no later work; no provider on reopen; uncertain crash is indeterminate | Cancellation/fault matrix with durable states and construction/submit counters |
| 11 | Cache-key field sensitivity and absence of sensitive durable material | Identity mutation tests plus sanitized SQLite/working-directory/privacy scan report |
| 12 | Immediate skeleton, progressive immutable slots, prior-complete retention, atomic final pointer | Publication crash/corruption tests and generation pointer history |
| 13 | Exact ordered contiguous section membership/route ownership and deterministic invalid fallback | Section/rollup adversarial tests with membership hashes and reduction-tree report |
| 14 | Complete bounded manifest and independently bounded lazy reads without full-map rebuild | API contract/size/latency tests with monolithic-builder trap |
| 15 | Revision on every read; cursor tamper/cross-use failure; typed stale 409 | API cursor security integration tests and exact error envelopes |
| 16 | Accepted browser grammar and state at all three profiles within DOM cap | Real Chrome report and exact-head outside-Git screenshots at 100%, 200%, and narrow |
| 17 | Old stale map retained; only deterministic path deltas produce `NEW`; lifecycle expires correctly | Multi-generation diff fixtures, prose-only negative case, browser toggle/state tests |
| 18 | Old records readable/immutable and v6 backup verified before v7 migration | Migration/rollback/backup hashes, Phase 03 compatibility tests, dependency/import scan |
| 19 | Every minimum shape and approved API/DOM/memory bound passes | Provider-free synthetic scale JSON/Markdown report with commands, timings, bytes, DOM, and peak memory |
| 20 | Full private completion and placeholder/coverage limits | Outside-Git MsDenvers report; sanitized counts/hashes/status summary recorded in `GOAL.md`/completion evidence |
| 21 | Protected bytes/size/time unchanged; no execution; private containment | Before/after fingerprints, execution-hook traps, Git/privacy/remote-request scan |
| 22 | Exact-head reviews, quality/release/CI, approved screenshots, open unmerged PR | Reviewer verdicts/commits, validation logs, user approval, GitHub run URL/head, PR state |

The expected command families are:

```powershell
.\.venv\Scripts\python.exe -m pytest -q <Phase-04-focused tests>
.\.venv\Scripts\python.exe -m pytest -q <M10/M11/M12/V2/storage/API/browser regressions>
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m mypy --strict src\renpy_story_mapper
.\.venv\Scripts\python.exe -m pip check
.\scripts\validate.ps1 -Tier Release -NoTimeout
git diff --check
```

Commands are planned evidence only until their exact results and heads are recorded in `GOAL.md`
or the completion report. Private and screenshot artifacts remain outside Git.

## Assumptions and conflicts

- Blocking conflict found and corrected: baseline criterion 8 required a “separately approved”
  loopback call, while the approved design says one frozen approval covers the explicitly disclosed
  fallback. This is a P1 contract/consent conflict because both approval flows cannot be true. The
  criterion now matches the approved design; no product code changed. Under the delegated rule, a
  contract contradiction requires `REVISE` even after the minimal correction, so a new exact
  contract checkpoint and repeated independent decision are required before implementation.
- P0/P1/P2 contract issues remaining after the correction: none identified. The repeat gate is a
  lifecycle requirement, not an unresolved design question.
- The hard 10,700 ceiling is interpreted as the whole serialized request under a versioned
  conservative counter; 8k/5k remain approximate raw-story targets. Treating 10,700 as raw source
  alone would not satisfy criterion 4.
- A preview-approved fallback is not a changed provider plan under criterion 6. Any unpreviewed
  provider, model, endpoint, adapter, or fallback permission changes the plan and needs a new
  preview/approval.
- Existing V2 Phase 02/03 contracts are intentionally too small for Phase 04: the source adapter's
  ordering, indivisible-choice planner, sequential total-call executor, single-current blob, and
  monolithic browser response are evidence of concrete extension seams, not accepted Phase 04
  behavior.
- The schema-v7 migration is justified by indexed, cross-record run/generation/query semantics that
  the single generic payload cannot meet efficiently at criterion-19 scale. The existing backup
  lifecycle is a usable seam but still needs v7-specific verification and failure tests.
- “Section” is a presentation partition within Level 1 Route Map, not a third semantic level.
  Detail/Evidence remains the only Level 2 transition.
- The current active native goal is intentionally absent. `PROJECT_STATE.md` requires the Phase
  Coordinator to create it only after a later semantic `PASS`; this reviewer did not create one.
- The delegation identifies this task as `gpt-5.6-sol` with High reasoning. The task API exposes no
  fast-mode selector, so fast mode is unavailable/unverified and is not claimed disabled by
  repository prose.
- Review discovery was limited to tracked repository authority, source, synthetic/public tests,
  and workflow files. The tracked `tests/private/` material and all outside-Git private paths were
  deliberately not opened.

## Gate decision

The approved architecture is otherwise bounded and implementable through verified M10/M11/M12,
SQLite, V2, API, and browser seams, and every criterion/exclusion has an executable evidence path.
However, the baseline approval contract contradicted the locked design at the refusal-fallback
consent boundary. The wording has been reconciled to the higher approved design, but the delegated
rule requires a revised checkpoint and repeated independent semantic decision. Broad product
implementation, native-goal creation, provider work, and private acceptance remain prohibited.

REVISE
