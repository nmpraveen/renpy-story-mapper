# M15.1 Phase 04 Track B report

Status: Awaiting final exact integrated-head review

Product baseline: `9e5088ea54dcd227e933fb14884d408596ff979b`

Required integration base: `5313a4cada975a62c2818bf82b2be548a9b3db53`

Track branch: `codex/m15-p4-track-b`

Integrated A+B+adapter code candidate: `e9ab282` (followed only by this report update)

The worker implementations began at the reviewed product checkpoint `9e5088e`. After Track A PR
#31 merged, Track B incorporated the exact current integration branch at `5313a4c`. Merge commit
`b509996` preserves Track A, the Phase Coordinator's lifecycle documentation, and the union of
Track A/Track B package exports. Commit `59c0932` makes that union Ruff-clean. No worker branch
pulled the earlier documentation-only checkpoint while product work was in progress.

## Visible tasks

| Role | Task ID | Worktree | Branch | Settings | State |
|---|---|---|---|---|---|
| Track B Coordinator | `019fa00d-1e77-7fd3-93d5-ee9761a5f662` | `C:/Users/prave/.codex/worktrees/bcc8/Renpy` | `codex/m15-p4-track-b` | inherited delegated coordinator | Final review pending |
| Worker B1 storage/durability | `019fa00f-8e20-7382-8dc9-2c1ce5d39975` | `C:/Users/prave/.codex/worktrees/d46a/Renpy` | `codex/m15-p4-track-b1-storage` | `gpt-5.6-sol`, High; fast mode unavailable/unverified | Exact head reviewed PASS |
| Worker B2 workflow/service/adapter | `019fa00f-b94c-7af1-9b10-1b67c64ea6fb` | `C:/Users/prave/.codex/worktrees/f258/Renpy` | `codex/m15-p4-track-b2-workflow`, then `codex/m15-p4-track-b2-adapter` | `gpt-5.6-sol`, High; fast mode unavailable/unverified | Workflow head reviewed PASS; adapter integrated for final review |
| Independent exact-head reviewer | `019fa00f-dad0-7b13-9454-9c9b44a0d098` | `C:/Users/prave/.codex/worktrees/70a9/Renpy` | detached exact candidates from `codex/m15-p4-track-b-reviewer` | `gpt-5.6-sol`, High; fast mode unavailable/unverified | Final integrated review pending |

The Codex task surface exposed model and reasoning selectors but no fast-mode selector. This report
therefore records fast mode as unavailable/unverified and does not claim repository prose changed
the running client setting.

## Frozen seam and ownership

Track B consumes frozen plan/job descriptors using `plan_id`, `scope_id`, `job_id`, `chunk_id`,
`authority_identity`, `serialized_request_identity`, and `cache_identity`. The storage and workflow
contracts do not import or reconstruct Track A occurrence/chunk-planning structures. The concrete
`DurableWorkflowRepository` translates only these frozen scalar/dataclass identities between
`WorkflowService` and `SqliteStoryMapV2Repository`.

- B1 owns schema-v7 migration/backup, indexed durable records, transactional leases/CAS, global
  six-slot claims, attempt reservation and recovery, immutable cache/generations/pages/selection,
  view state, and privacy-safe persistence.
- B2 owns zero-submit preview/approval, lazy fake-provider construction, fixed-six execution,
  cancellation/recovery, exact indeterminate retry approval, selective replacement review,
  refusal-only loopback fallback, finite accounting, and the concrete durable workflow adapter.
- No batching, adaptive ramp, recursive provider splitting, attempt-number reuse, M13 scheduler,
  Track C semantic rollups/read API, Track D browser UI, M14, historical narrative/organization
  code, private source, or live provider is present.

## Reviewed worker lineage

### B1 storage

Worker head `20e3c63c84d3f848999c7a89c5fe09897ba0c748` passed independent exact-head
review with `P0=0, P1=0, P2=0, P3=0`. Its reviewed commits were replayed patch-identically as:

| Worker commit | Integrated commit | Purpose |
|---|---|---|
| `aa71721` | `43d9592` | schema-v7 durable storage and repositories |
| `e9d344a` | `a34fbb3` | recovery, retry, authority, privacy, accounting invariants |
| `79e1a85` | `762c028` | durable attempt/cancellation transitions |
| `e4b323a` | `c2de808` | embedded absolute-path sanitization |
| `20e3c63` | `bf74413` | recursive mapping-key privacy validation |

Final B1 review evidence included 57 dedicated passes, 326 public V2 passes with 9 opt-in browser
skips, 76 adjacent persistence passes, 140/140 absolute-path key/value rejections, 49/49 forbidden
raw-field rejections, Ruff, strict mypy, pip check, whitespace, privacy, and architecture passes.

### B2 workflow

Worker head `4334948b899ff0bb9f9149f9bc64b5ced830fbd4` passed independent exact-head
review with `P0=0, P1=0, P2=0, P3=0`. Its reviewed commits were replayed patch-identically as:

| Worker commit | Integrated commit | Purpose |
|---|---|---|
| `a622f25` | `68b8d37` | workflow contracts, protocols, service, fake-provider tests |
| `989c37f` | `a8fcc65` | recovery races, cancellation, cache, and privacy |
| `7fb2177` | `ee3071d` | exact indeterminate retry call kind |
| `16a501e` | `bd257c9` | finite approved supplemental retry capacity |
| `4334948` | `a28b9de` | release capacity after definite non-transmission |

Final B2 review evidence included 50 focused passes, 16 accumulated fault/reviewer matrix passes,
319 public V2 passes with 9 opt-in browser skips, 134 adjacent passes, fixed-six/two-service
exclusion, Ruff, strict mypy, pip check, whitespace, privacy, and architecture passes.

### Durable adapter

Worker commit `324e0c43b7742d055856651407fa9c1e3fe99eaa` was replayed as `097460a`.
It adds `workflow_repository_adapter.py`, its real-SQLite integration tests, and default-preserving
generic repository hooks needed for approved cache revalidation and exact frozen cache identity.
The adapter branch reported 122 focused passes, 95 provider/project/V2-adjacent passes, 72
persistence passes with 9 opt-in browser skips, a 140-pass synthetic Track A+B+adapter selection,
Ruff, strict mypy over all 114 source files, pip check, whitespace, privacy, and architecture passes.
Final integrated review then found two adapter/storage defects: process-local validated-job cache
routing and non-durable supplemental retry markers. Worker correction
`aa0f57ea31f473e280ceab1e59e3aa2e4a1df40e` was replayed as `e9ab282`. It removes the
process-local routing map, binds cache writes to the exact claim, persists mode-specific cache
routing on the job, persists/reloads retry lineage and supplemental-use fields on attempts, and
counts only durably marked possible-transmission attempts against supplemental capacity.

## Review correction history

Independent review rejected earlier candidates until the following defects were closed:

- B1: reserved/no-send versus uncertain recovery, same-kind retry, review/fallback retry approval,
  cancellation transition bypass, generation authority binding, exact accounting types/call count,
  and absolute paths embedded in nested values or mapping keys.
- B2: lost refusal-fallback kind, one-call not-transmitted duplication, cancellation submit race,
  POSIX privacy leakage, unread loopback cache, lost review/fallback retry kind, calls=1
  indeterminate retry capacity, and provisional capacity lost after definite non-transmission.
- Adapter failing-first tests: same-execution reclaim after definite no-send and the claimed-job
  transition required for approved cache revalidation.
- Final integrated review at `0942ea8` rejected process-local cache routing and inferred rather
  than persisted supplemental retry occupancy (`P0=0, P1=2, P2=0, P3=0`). Correction `e9ab282`
  closes the cloned-adapter, identical-result concurrency, loopback recovery, mixed calls=0/1,
  attempt reload, and no-send supplemental-release reproductions.

No rejected head remains the accepted tip. The complete reviewed worker chains, adapter, and its
bounded durable-authority correction are present. The corrected combined candidate still requires
a fresh exact-head review after this report update.

## Changed files relative to integration base `5313a4c`

- `src/renpy_story_mapper/project.py`
- `src/renpy_story_mapper/storage.py`
- `src/renpy_story_mapper/story_map_v2/__init__.py`
- `src/renpy_story_mapper/story_map_v2/durable_repository.py`
- `src/renpy_story_mapper/story_map_v2/workflow_contracts.py`
- `src/renpy_story_mapper/story_map_v2/workflow_protocols.py`
- `src/renpy_story_mapper/story_map_v2/workflow_repository_adapter.py`
- `src/renpy_story_mapper/story_map_v2/workflow_service.py`
- `tests/test_m11_persistence.py`
- `tests/test_m12_persistence.py`
- `tests/test_m13_persistence.py`
- `tests/test_story_map_v2_durable_repository.py`
- `tests/test_story_map_v2_phase04_workflow.py`
- `tests/test_story_map_v2_workflow_repository_adapter.py`
- `docs/milestones/M15_PHASE_04/TRACK_B_REPORT.md`

## Coordinator evidence

Commands use Windows CPython 3.12.10 and `PYTHONPATH=src` because this worktree has no local
`.venv`. The initial baseline command without `PYTHONPATH` collected no tests and made no change.

- Baseline storage/preview/provider/failing-first selection at `9e5088e`: `52 passed`.
- Reviewed B1+B2 focused suites immediately after integration: `107 passed`.
- Storage/project/provider/persistence plus every public V2 test before Track A merge:
  `505 passed, 9` opt-in browser skips.
- Track A+B focused suites after integrating `5313a4c`: `130 passed`.
- Track A+B+adapter focused suites after durable-authority correction: `149 passed`.
- Corrected storage/project/provider/persistence plus every public V2 test:
  `547 passed, 9` opt-in browser skips.
- Corrected targeted durability/privacy/fault/retry/cache selection: `82 passed, 44 deselected`.
- Ruff over `src tests scripts`: PASS.
- Strict mypy over all 118 source files: PASS.
- `pip check`, `git diff --check`, and forbidden-import architecture scan: PASS.

Independent corrected exact-head review is the remaining local gate. Push and PR creation remain
blocked until that review passes with `P0=P1=P2=0`. The PR target is
`codex/m15-phase04-full-game`, never `main`, and the coordinator will not merge it.

## Assumptions, conflicts, and remaining cross-track work

- File-backed SQLite is required for six-thread service execution. The adapter reuses
  `Project.story_map_v2_repository()` and opens short-lived worker connections.
- The only integration conflict was the expected shared `story_map_v2/__init__.py` exposure seam;
  it was resolved as the union of Track A StoryPlan and Track B durable exports, then sorted.
- No live provider was constructed or called, and no private-source file was inspected.
- Track A supplies frozen occurrence/chunk descriptors through the stable seam. Track C still owns
  semantic sections/rollups/read APIs and Track D owns browser UI. Their work is outside Track B.
- The Phase Coordinator retains milestone lifecycle/goal ownership and final cross-track closure.
