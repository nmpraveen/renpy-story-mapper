# M15.1 Phase 02 task ledger

Integration branch: `codex/m15-msday1-narrative-map`

Pull request: [PR #26](https://github.com/nmpraveen/renpy-story-mapper/pull/26), draft and
unmerged.

Lifecycle: `Blocked in Verification`

| Task | Owner | Dependencies | Affected area | Status / evidence |
|---|---|---|---|---|
| Phase 02 preflight | Coordinator | User starts Phase 02 handoff | Read-only repo/PR/evidence | Complete: clean required worktree at `f914908`; branch 136 commits ahead of remote; PR #26 open/draft/unmerged at `bc9a38c`; Phase 01 package and recorded source/archive fingerprints present |
| Lock Phase 02 contract | Coordinator | Preflight | M15 lifecycle docs | Complete: one done condition, deliverables, 16 acceptance criteria, exclusions, evidence, provider ceilings, topology, and handoff rules recorded |
| Freeze simple V2 design | Coordinator | Contract | `PHASE_02_DESIGN.md` | Complete: new package boundary, lower-level authority, compact records, overlay, partial behavior, provider states, seams, and forbidden Stage H/E dependencies recorded |
| Create native Phase 02 goal | Coordinator | Locked contract | Goal service / project state | Complete: active goal/task `019f9676-c357-7803-a891-f03782bbb8ee` exactly matches the contract done condition |
| Early contract review | Visible read-only task `019f967d-8800-79e2-9dea-5f2412f6eecf` | Locked contract and design | Docs and read-only source discovery | Complete: `REVISE` at `df75532` with four P1s/no P0-P2; one bounded correction; same-task rereview `PASS` at `4d32f08` with no unresolved P0-P2 |
| Shared contracts and failing-first tests | Coordinator | Early reviewer `PASS` | `story_map_v2` seams/tests | Complete at `e72fe41`: mapper schema, versioned records, Track A/B signatures, transitive forbidden-dependency gate; five contract tests pass; seven Track A and six Track B tests fail only at explicit stubs; Ruff and strict mypy pass |
| Core authority/storage seam correction | Coordinator | A1/A2 exact-authority, packet, provenance, and preview audits | `SourceSpan`, `StoryChunk`, execution, preview, and core contracts/generalized fixtures | Complete: failing-first tests proved non-choice event status, the compact mechanics packet, validated mapper branch/scope meaning, exact execution provenance, and local endpoint confirmation lacked durable seams. Corrected records require Python-owned reachability/warnings, canonical mechanics JSON, anchored branch outcomes, retained scope text/provenance, and an exact local model/endpoint pair in the confirmation hash. Nine shared contract tests, Ruff, strict mypy, and whitespace pass; no guessed default was introduced. |
| Frozen partial-assembly fixture correction | Coordinator | A2 strict duplicate-identity validation | Track A failing-first test only | Complete: the old two-span fixture planned one chunk and supplied its identity twice. The corrected generalized fixture uses two 6,000-token natural-boundary spans, asserts two distinct chunk identities, and retains strict duplicate-identity rejection. |
| Track A implementation and exact-head review | Visible coordinator `019f968f-e973-7380-9a26-0443389993a9`; worktree `C:/Users/prave/.codex/worktrees/981c/Renpy` | Shared base `43c6251` | Provider-neutral V2 core | Complete: reviewed exact head `319d13e99fe1eed99b3e6cbc51695d6ca7d37e26`; reviewer task `019f96b9-f91e-7b71-b31e-2224fb174d76` returned `PASS` with no P0-P2; integrated through `609813b` |
| Track B implementation and exact-head review | Visible coordinator `019f968f-e973-7380-9a26-0464d6f7073f`; worktree `C:/Users/prave/.codex/worktrees/0ec5/Renpy` | Shared base `43c6251` | Execution/fallback policy | Complete: reviewed exact head `ca9cd4afd0f27d7926ed5d246f3aa738267816ac`; reviewer task `019f96c6-09f2-7262-94fa-f2c160f96c25` returned `PASS` with no P0-P3; integrated through `44af018` |
| Integration and provider-free verification | Coordinator | Reviewed Track A/B commits | Integrated package/tests | Complete at `cbbe3ef`: source chronology and conservative story-choice inference corrected after private preflight; 287 focused/relevant M10-M12/workflow tests passed; Ruff, strict mypy, import isolation, and whitespace passed |
| Private Day 1 acceptance | Coordinator | Provider-free integration pass | Outside-Git acceptance artifacts | Blocked: zero-submit confirmation `2d6b67f7425b43a84ba913078b36ecf8205aa3f97fcfe68ceceaa65b8f72fa98` proved 2 calls, 9,376-token maximum, exact Luna/High/fast-off, no fallback, and 4 story choices/8 arms. The one authorized execution returned two sanitized transport failures before any hosted submission (`hosted_attempts=0`), so the preserved core is honest `partial` with 0/2 complete chunks. No retry or second story run occurred. |
| Final exact-head review | Separate visible read-only reviewer | Frozen integration head/artifacts | Full Phase 02 contract | Pending |
| Lifecycle, commit, PR checkpoint | Coordinator | Final review pass | Docs/Git/PR #26 | Blocked; goal remains active and PR #26 remains draft/unmerged because criteria 10-11 and 14-15 are not complete |

Historical Stage H/E, adjacent-gap, atom/hierarchy, Phase 01, and prior review tasks remain readable
in Git history and earlier M15 evidence. They are not active Phase 02 tasks or acceptance proof.

Every visible Phase 02 task uses `gpt-5.6-sol` with High reasoning. The task creation API has no
fast-mode selector, so that setting is recorded unavailable/unverified.
