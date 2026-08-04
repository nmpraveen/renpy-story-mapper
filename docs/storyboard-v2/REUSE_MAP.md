# Phase 01 reuse map

Status: active for the AI-first canary; documentation only

This map records which existing repository modules may contribute to the new
`src/renpy_story_mapper/storyboard/` path. It is a boundary, not an implementation
plan or proof that a module is already generic enough for every Ren'Py game.

## Decision rules

- **Reuse now** means a bounded low-level surface is suitable for source recovery,
  exact-text preservation, or direct syntax evidence in Phase 01.
- **Narrow adapter/proof** means the old module may be studied or wrapped behind a
  small new interface only after focused tests prove its behavior is generic. Its
  existing schema or story authority does not become the new product authority.
- **Bypass** means do not import, extend, or make the Phase 01 canary depend on the
  module. Keep it intact as historical/legacy code.

The new path must keep game inputs read-only, keep generated output outside the
input tree and Git, and contain no game title, character, dialogue line, label,
expected count, fixed AI batch count, or game-specific exclusion.

## Phase 01 target seam

```text
game folder / .rpy / .rpyc / .rpa
  -> read-only ingestion and recovery
  -> inert source model and exact evidence index
  -> AI reconnaissance, profile, and semantic story analysis
  -> deterministic citation/coverage/menu-arm validation
  -> new static canary renderer
```

AI analysis and the new evidence/validation/rendering contracts do not exist in
the legacy package yet; they belong in the isolated `storyboard` package. The
legacy web application, database workflows, and editorial-only AI layers are not
the target seam.

## Reuse now

| Path | Reusable surface | Reason and boundary |
|---|---|---|
| `src/renpy_story_mapper/ingestion/contracts.py` | `IngestionOptions`, `IngestionPlan`, `IngestionSource`, `SourceProvenance`, and related result types | Provides source tier, locator, hash, line-basis, recovery-warning, and read-only input contracts needed to preserve provenance. Do not treat the contracts as a durable project schema. |
| `src/renpy_story_mapper/ingestion/service.py` | `inspect_input()` and `ingest_input()` for game folders, readable scripts, and archives | Performs deterministic source precedence, path normalization, content hashing, bounded recovery, and source immutability checks. The `.rsmproj` branch and database behavior are outside Phase 01 and must not be pulled into the new path. |
| `src/renpy_story_mapper/ingestion/runtime.py` | `recover_compiled()` and its bounded helper-process/cache safeguards | Safe reusable boundary for `.rpyc` recovery: pinned runtime, sanitized environment, Windows Job Object limits, timeout/size limits, and explicit reconstructed-source provenance. It must never execute creator code or mutate the supplied game. |
| `src/renpy_story_mapper/ingestion/_vendor/unrpyc/` | Pinned inert recovery bundle only | The bundle is already hash-pinned and used behind `ingestion.runtime`; retain it as a recovery implementation, not as a general Ren'Py runtime or semantic interpreter. |
| `src/renpy_story_mapper/ingestion/helper.py` | Safe helper-process argument/environment and bounded recovery utilities | Reusable only through the ingestion runtime boundary; it keeps recovery outside the main process and avoids secret or broad environment inheritance. |
| `src/renpy_story_mapper/ingestion/export.py` | `export_recovered_sources()` and provenance sidecars | Useful when a canary needs reconstructed `.rpy` files outside the input tree. The export destination must remain separate from the supplied game and is not itself the evidence index. |
| `src/renpy_story_mapper/ingestion/errors.py` and `src/renpy_story_mapper/errors.py` | Input/recovery error types | Small, non-semantic error vocabulary that can be reused or copied without importing legacy workflows. |
| `src/renpy_story_mapper/rpa.py` | `RpaArchive`, `RpaEntry`, `fingerprint_file()`, restricted index parsing, streaming entry reads | Directly matches the safe archive/source-recovery boundary. It rejects unsafe paths, limits archive sizes, fingerprints before/after reads, and never runs archive contents. |
| `src/renpy_story_mapper/importer.py` | `iter_utf8_lines()` and `inventory_archive()` | Supplies incremental strict UTF-8 line recovery, source/compiled pairing, archive manifest facts, and source-preferred selection without interpreting story meaning. |
| `src/renpy_story_mapper/model.py` | `SourceSpan`, `Statement` variants, `Label`, `Menu`, `If`, `ScriptModule`, and their exact source text | This is a compact inert syntax model with source locations, menus, conditions, transfers, opaque blocks, and unknown statements. It is a strong starting point for a new evidence index, provided opaque/unsupported records remain explicit. |
| `src/renpy_story_mapper/parser.py` | `parse_script()` / `RenpySubsetParser` as a conservative syntax inventory | The parser is inert, preserves physical spans and source lines, recognizes labels, menus, conditions, jumps, calls, returns, and Python/unsupported blocks as opaque, and emits diagnostics. Its supported subset is not complete Ren'Py semantics; every unsupported construct must remain evidence/unresolved for AI. |

These modules provide facts and provenance only. They do not decide scene meaning,
character identity, variable meaning, route consequence, ending status, or hidden
content.

## Narrow adapter/proof

| Path | Possible bounded use | Required proof / reason not to import directly |
|---|---|---|
| `src/renpy_story_mapper/graph.py` | Adapt `build_graph()` output into canary control-flow evidence | It emits useful stable node/edge/source records and explicit missing/dynamic/unresolved edges, but it defaults to `start`, contains legacy call-continuation summary edges, and uses an M01 graph schema. Prove entry-label handling, calls/returns, scope, menus, and exact coverage on the canary before wrapping it. |
| `src/renpy_story_mapper/control_flow.py` | Adapt `analyze_control_flow()` / `derive_story_quotient()` for loops, branches, regions, ownership, and state-lineage facts | It normalizes interprocedural control flow without evaluating expressions, but its region and route semantics are complex and legacy-shaped. Focused tests must prove generic nested ownership, ambiguous shared regions, loops, and unresolved dynamic behavior before any result is authoritative. |
| `src/renpy_story_mapper/state.py` | Adapt raw requirement/effect/evidence extraction | It preserves `PROVEN`, `POSSIBLE`, and `UNRESOLVED` evidence and safely parses literal assignments/conditions, but its category keywords and creator-call heuristics are assumptions. Reuse raw evidence only until AI/profile analysis establishes game-specific meaning. |
| `src/renpy_story_mapper/canonical_graph_contract.py` | Borrow stable-ID, source-evidence, and explicit reachability/diagnostic patterns | The contract is tied to M10 canonical schema and durable authority bindings. Do not make the Phase 01 package depend on M10 schema versions or canonical payloads. |
| `src/renpy_story_mapper/canonical_graph.py` | Narrowly test selected canonical fact algorithms if the canary requires them | This is the old graph authority and previously failed on a current unseen-game baseline through `canonical_graph`; it also depends on legacy route/state records. Preserve failures and require a generic adapter proof before reuse. |
| `src/renpy_story_mapper/route_map.py` | Potentially adapt source-grounded route/edge facts after control-flow proof | It projects old canonical/M12 records into route lanes and human-facing route nodes. Do not import its labels or presentation semantics as Phase 01 truth; prove only the minimal source-linked fact subset needed by the canary. |
| `src/renpy_story_mapper/story_metadata.py` | Optional raw literal hints for reconnaissance | It safely extracts literal characters, defaults, screen text, memory titles, and state hints with evidence, but its constructors and keyword categories are heuristic and incomplete. Treat results as cited input to AI, never as final semantic truth. |
| `src/renpy_story_mapper/story_map_v2/source_adapter.py` | Study/adapt source-span and choice-lineage checks if a later canary needs them | It converts already-validated M10/M11 canonical authority into a V2 `StoryScope`; it does not recover source independently and is bound to legacy authority hashes and scene models. No direct dependency until a focused adapter test proves the boundary. |
| `src/renpy_story_mapper/narrative/evidence.py` | Reuse the idea of bounded evidence-handle and claim-DAG validation | Its `AuthorityReference`, M13 claim types, handle formats, and persistence assumptions are old-schema-specific. Copy or adapt only the cycle, scope, unknown-reference, and result-limit checks into the new analysis contract. |
| `src/renpy_story_mapper/storage.py` | At most copy the deterministic `canonical_json()` validation pattern | The module is a durable SQLite schema/migration layer. A static Phase 01 output has no need for its database; no `.rsmproj` or payload collection may become a prerequisite. |
| `src/renpy_story_mapper/cli.py` | Add one narrow future command-registration seam | The existing CLI wires legacy analyze/project/recovery flows together. Do not extend those flows; only register the eventual `storyboard GAME_PATH --output OUTPUT_DIRECTORY` command after the isolated package exists. |

## Bypass for Phase 01

| Path | Reason |
|---|---|
| `src/renpy_story_mapper/semantic.py` | Hard-coded deterministic scene/dialogue grouping is the old Phase 1 presentation model. The reset gives AI authority to infer scene boundaries, characters, meanings, and narrative grouping; this module must not become a universal semantic interpreter. |
| `src/renpy_story_mapper/ai_story_map.py` and `src/renpy_story_mapper/bounded_window.py` | These are optional/editorial AI and bounded-window projections over M07–M12 authority. They do not provide the new AI reconnaissance/profile/story-analysis contract and would keep the old authority boundary. |
| `src/renpy_story_mapper/project.py`, `src/renpy_story_mapper/project_analysis.py`, and `src/renpy_story_mapper/analysis_phases.py` | Durable SQLite project lifecycle, incremental refresh, M01–M12 phase persistence, and old analysis orchestration are explicitly outside the thin static canary. |
| `src/renpy_story_mapper/m07_model.py`, `src/renpy_story_mapper/m07_workflow.py`, `src/renpy_story_mapper/m11_*.py`, and `src/renpy_story_mapper/m12_*.py` | Milestone-specific durable workflow, scene publication, route solving, cache, and correction layers. Preserve them as historical evidence; do not revive or extend them for the new product. |
| `src/renpy_story_mapper/story_organization.py` and `src/renpy_story_mapper/organization_workflow.py` | Old organization/parallel-summary orchestration. Phase 01 needs one small AI analysis path and focused repair/validation, not the previous provider/batch workflow. |
| `src/renpy_story_mapper/narrative/` except the isolated validation idea in `narrative/evidence.py` | The package is the M13 provider, consent, batching, persistence, scheduler, prompt, and claim workflow. It is a provider platform and depends on M10–M12 authority, both excluded from this canary. |
| `src/renpy_story_mapper/organization/` | M05/M07 organization providers, chunking, parallelism, persistence, and schemas are legacy orchestration and are not a prerequisite for AI interpretation. |
| `src/renpy_story_mapper/story_map_v2/` except the possible `source_adapter.py` proof described above | The remaining directory is durable Story Map V2 assembly, transports, persistence, publication, whole-game corridors, reader contracts, workflow services, and product UI. The reset explicitly bypasses this architecture. |
| `src/renpy_story_mapper/inspection_projection.py` and `src/renpy_story_mapper/presentation.py` | Durable canonical/route projections and the old database-backed presentation service. Phase 01 needs a new static renderer over the canary output, not the existing reader projection. |
| `src/renpy_story_mapper/web/` and `src/renpy_story_mapper/web/static/` | Qt/loopback web application, old API contracts, Story River assets, and browser workflow. Do not extend the old web app or use it as proof of the new static storyboard. |
| `src/renpy_story_mapper/evaluation/` | M08 comparison artifacts and browser/provider evaluation contracts are downstream acceptance machinery, not the Phase 01 evidence index or focused validator. Borrow no required dependency from them. |
## Phase 01 guardrails for any adapter

Any adapter admitted after this map must demonstrate, on an unfamiliar synthetic
fixture and the selected real canary, that it:

1. preserves stable IDs, exact source text, and file/line evidence;
2. reports unsupported, dynamic, missing, or ambiguous behavior instead of guessing;
3. accounts for every menu arm and can expose parser/AI disagreement;
4. does not require a known game name, label, dialogue line, or fixed count; and
5. can be removed without reviving Story River, durable Story Map V2, or a provider platform.

Until those checks pass, the new storyboard package must use the reuse-now surface
directly and keep all other classifications out of its runtime imports.
