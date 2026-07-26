# M15.1 Phase 04 Track A report

Date: 2026-07-26

Status: Reviewed Track A handoff; not Phase 04 completion.

## Identity and pull request

- Exact product baseline: `9e5088ea54dcd227e933fb14884d408596ff979b`.
- Coordinator branch: `codex/m15-p4-track-a`.
- Independently reviewed product head: `ec38ca76e3245d7dc00e5520669d1a729cee9770`.
- Reviewed product tree: `059086d38ebdd22f9a28e5c8a6ceb9b80c4515a0`.
- Pull request: [#31](https://github.com/nmpraveen/renpy-story-mapper/pull/31), open and non-draft.
- Pull-request base: `codex/m15-phase04-full-game`, never `main`.
- Merge state: unmerged. Track A does not authorize an independent merge.
- The Phase Coordinator's later documentation-only integration commits were intentionally not
  pulled into the Track A worker branches; PR #31 targets the branch that owns those records.

## Visible tasks and settings

Every task was explicitly dispatched with `gpt-5.6-sol` and High reasoning. The task API exposed
no fast-mode selector, so fast mode is unavailable/unverified rather than claimed disabled.

| Role | Task ID | Worktree | Branch / reviewed handoff |
|---|---|---|---|
| Track A Coordinator | `019fa00d-1e55-79e0-95b0-c88f8fd89919` | `C:/Users/prave/.codex/worktrees/6321/Renpy` | `codex/m15-p4-track-a` |
| Worker A1 | `019fa00e-c8e5-7141-8c83-d043b27d9d34` | `C:/Users/prave/.codex/worktrees/9f93/Renpy` | `codex/m15-p4-track-a1`; correction `codex/m15-p4-track-a1-r1` |
| Worker A2 | `019fa00e-c8e9-7422-bce8-adc0b692ff40` | `C:/Users/prave/.codex/worktrees/fe82/Renpy` | `codex/m15-p4-track-a2`; integration/correction branches recorded below |
| Independent reviewer | `019fa00e-c967-7e71-a7e4-151e1cfcb498` | `C:/Users/prave/.codex/worktrees/ad4a/Renpy` | `codex/m15-p4-track-a-review`; detached exact-head reviews |

## Delivered scope

- Frozen occurrence-aware `StoryPlan`, `StoryScopeDescriptor`, `StoryPlacement`, and bounded loop
  contracts over exact M10/M11 bindings.
- M11-first chapter, lane, scene, and call-occurrence order before source locator tie-breakers.
- Distinct shared-callee occurrence placements, persistent child scopes with exact split anchors,
  nested/local choice ancestry, endings, unresolved records, and exact coverage identities.
- Exact provider-free adapter from the trusted graph-derived `StoryScope` and `StoryPlan` into the
  chunk-planning projection. Caller-mutated scope material fails closed.
- Frozen scope/lane and atomic scene/call/arm-lineage groups that preserve every Story Placement
  exactly once and split only at authorized deterministic boundaries.
- Canonical self-verifying `StoryChunkPlan`, strict deserialize/reconstruct checks, approximately
  8,000-token normal and 5,000-token branch-heavy targets, and a conservative complete serialized
  request ceiling of 10,700.
- Oversized persistent, local, and nested choice segmentation with one Python-owned parent;
  provider-free structural fallback only for an atomic group that itself exceeds the ceiling.
- Frozen-plan assembly with exact plan/request binding, predetermined structural fallback slots,
  foreign/duplicate result rejection, and an executable trap proving assembly does not replan.
- Public failing-first fixtures covering reversed physical versus narrative order, a shared label
  called twice, persistent lanes, local/nested choices, loops, endings, unresolved arms, exact
  no-omission/no-duplication coverage, and safe material above 10,700.

## Commit provenance

| Purpose | Worker commit | Integrated commit |
|---|---|---|
| A1 Story Plan contracts and public fixture | `60213913dc69b148f234abc7e67081c04af146e8` | `4943bd2` |
| A2 failing-first chunk cases | `3338d6061c5b14e0c225029f3bb8a263c96ed901` | `faecc5b` |
| A2 frozen chunk plan and assembly | `e4dceca9f592c4c9fe74a92786708a813f71828b` | `71481fc` |
| A1/A2 adapter failing-first seam | `7016f2a55f3bd3c508aa021923947dce4474934d` | `7016f2a` |
| A1/A2 adapter and atomic grouping | `8c7027e4362444bf0806db3f92419ef49349e5d0` | `8c7027e` |
| Reviewer-round A1 failing tests | `82c6c4dac95e33eccfcd711b8c8bc2ccd024e758` | `a506cd4` |
| Reviewer-round A1 authority correction | `e480a78344f071716fd62a604ee407844adcc6da` | `4ab29ea` |
| Reviewer-round A2 failing tests | `dc47c51b3c24746733f2ffe7f8ba4e62a4d5b5c2` | `b3151fc` |
| Reviewer-round A2 arm-boundary correction | `fb8eca8dcc60c0248d8880c4664734ab3f52b675` | `ec38ca7` |

## Changed files

- `src/renpy_story_mapper/story_map_v2/__init__.py`
- `src/renpy_story_mapper/story_map_v2/source_adapter.py`
- `src/renpy_story_mapper/story_map_v2/story_plan.py`
- `src/renpy_story_mapper/story_map_v2/phase04_chunk_adapter.py`
- `src/renpy_story_mapper/story_map_v2/phase04_chunk_plan.py`
- `src/renpy_story_mapper/story_map_v2/phase04_assembly.py`
- `tests/fixtures/story_map_v2/phase04_occurrence_plan.rpy`
- `tests/fixtures/story_map_v2/phase04_chunk_planning.json`
- `tests/test_story_map_v2_phase04_story_plan.py`
- `tests/test_story_map_v2_phase04_chunk_adapter.py`
- `tests/test_story_map_v2_phase04_chunk_planning.py`

No M10/M11/M12 authority implementation, schema-v7 persistence/workflow, semantic rollup,
publication/API, browser UI, provider, M13, M14, historical `organization/` or `narrative/`, or
private-content file changed.

## Verification evidence

The shared CPython 3.12 virtual environment is installed from the main checkout, so every command
prepended this worktree's absolute `src` directory to `PYTHONPATH` before execution.

| Check | Result |
|---|---|
| `pytest -q tests/test_story_map_v2_phase04_story_plan.py tests/test_story_map_v2_phase04_chunk_adapter.py tests/test_story_map_v2_phase04_chunk_planning.py` | 23 passed |
| All public `tests/test_story_map_v2*.py` | 292 passed; 9 existing opt-in browser cases skipped |
| All public `test_m10*`, `test_m11*`, and `test_m12*` files, excluding private files | 225 passed; 1 existing opt-in browser case skipped |
| `ruff check src scripts <all public Python tests>` | Passed |
| `mypy --strict src/renpy_story_mapper` | Passed across 113 source files |
| `pip check` | No broken requirements |
| `git diff --check 9e5088e..ec38ca7` | Passed |
| Changed-path privacy/scope scan | Passed; no private or forbidden subsystem path |
| Forbidden dependency import scan | Passed; no historical semantic, M13, storage/project, API/browser, or provider dependency |

The initial reviewer rejected exact head `8c7027e` with P0=0, P1=3, P2=0, P3=0 for self-parent
loop lineage, same-scene arm grouping that hid a legal split, and acceptance of caller-mutated
StoryScope text. Both workers added failing-first public regressions and corrected only their owned
seams. The same reviewer then detached to `ec38ca7`, reran the original probes and full bounded
matrix, and returned `PASS` with P0=P1=P2=P3=0. No reviewer file or commit was created.

## Assumptions, defects, and conflicts

- No known Track A defect remains after exact-head rereview.
- No integration conflict occurred. The A1 and A2 correction ranges changed separate production
  seams and were cherry-picked in failing-test-then-fix order.
- `StoryPlan.normalized_dict()` is information-complete and contains no raw source text. Track B
  owns canonical persisted reconstruction/identity verification under schema v7; Track A assembly
  consumes the independently strict reopened `StoryChunkPlan` and does not replan.
- A repeated scene/context/occurrence/arm-lineage tuple that reappears non-contiguously receives a
  distinct ordinal-bound atomic group; intervening narrative or calls are never merged away.
- Truly indivisible atomic material above 10,700 uses structural fallback. Cross-track execution
  and private acceptance must still enforce the final rule that no choice, route, rejoin, ending,
  or new branch remains unsummarized.
- No provider was constructed or called. No private source, private fixture, provider response,
  raw prompt, credential, private screenshot, or machine-specific private path was inspected or
  committed.

## Remaining cross-track work

- Track B: schema-v7 plan/chunk persistence, strict Story Plan reconstruction, runs/jobs/attempts,
  consent, cache, cancellation, leases, and recovery.
- A/B integration: freeze the persisted plan/job/publication seam and prove reopen/resume uses
  these exact Track A identities without replanning.
- Track C: validation/review coordination, immutable generations, sections/rollups, locators,
  deterministic `NEW`, and bounded APIs.
- Track D: lazy browser workflow, view state, scale/browser acceptance, and screenshots.
- Phase Coordinator: synthetic scale, private full-game acceptance, protected-input fingerprints,
  final cross-track review, user visual approval, Release/package, CI, and the single Phase 04 PR.
