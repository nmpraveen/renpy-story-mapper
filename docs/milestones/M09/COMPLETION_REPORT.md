# M09 Completion Report — Static Story Metadata Enrichment

Date: 2026-07-13

Branch: `codex/m09-static-story-metadata`

Baseline: `d8ec4d258cff28d66aecfd951e5a831e1e9818a1`

PR state: [PR #16](https://github.com/nmpraveen/renpy-story-mapper/pull/16) merged on 2026-07-13 at
`f327896c0ff9c05177eae7d8f5e82e38f38f3e45`. The earlier open/unmerged wording was stale and is
corrected from verified GitHub merge metadata.

## Outcome

M09 is complete. A selected game folder containing exact `scripts.rpa` now treats that archive as
the sole authority for chronology and connectivity. Exact `extras.rpa` may contribute a small,
static, advisory metadata layer, but its replay/gallery labels never become story routes. Loose
`.rpy`/`.rpyc` files and unrelated archives are also excluded from canonical analysis whenever
`scripts.rpa` is present.

The analyzer can now attach readable character names, declared state defaults, supported variable
meanings/categories, and optional exact-key scene titles to facts already established by the
deterministic pipeline. These names appear in the supported browser Route Map and Detail/Evidence
flow. They do not create nodes, edges, gates, effects, routes, merges, loops, or endings.

## Delivered product flow

1. The user selects a Ren'Py game folder or supported source input.
2. If exact `scripts.rpa` is present, it alone supplies canonical story sources.
3. Exact `extras.rpa` is recovered through the existing bounded Unrpyc path into a secondary,
   metadata-only source lane.
4. A non-executing static extractor recognizes only supported literal forms: character aliases,
   scalar defaults, adjacent state labels, a narrow allowlisted character-stat form, and optional
   literal memory/title records.
5. Every accepted item retains its source locator, fingerprint, line basis, and exact span.
6. Metadata is persisted with the project and refreshed independently from graph analysis.
7. The supported browser can show exact scene-title matches, speaker display names, and readable
   state-variable names while retaining technical topology and applied AI titles.
8. Dynamic, malformed, conflicting, or ambiguous metadata fails closed and remains unresolved.

## Authority and safety boundaries

- `scripts.rpa` remains the only story authority in the paired game-folder workflow.
- `extras.rpa` is advisory metadata only. Replay content is never added to M01/M02/M06 chronology.
- Images, audio, fonts, shaders, caches, and unrelated archives are neither parsed nor used.
- No embedded Ren'Py, screen, or game Python executes.
- Metadata extraction uses bounded source bytes, record counts, and diagnostics; cancellation and
  existing recovery limits remain in force.
- Duplicate/conflicting aliases, hints, or scene-title keys are suppressed rather than selected by
  input order.
- Explicit user state display/category edits override extracted hints and remain reversible.
- Opening, rendering, searching, and refreshing metadata constructs no AI provider and transmits
  no story text.

## Read-only MsDenvers result

Final output: `artifacts/M09/msdenvers-metadata-final`

| Measure | Verified result |
|---|---:|
| Canonical story sources | 52 |
| Secondary metadata sources | 5 |
| Source inventory / derivations | 57 / 57 |
| Usable character aliases | 84 |
| Declared scalar defaults | 109 |
| State hint records | 134 |
| Readable state variables | 15 |
| Optional scene/memory titles retained | 13 |
| Bounded unresolved metadata diagnostics | 44 |
| Replay labels in canonical graph | 0 |
| Provider calls | 0 |
| SQLite integrity | `ok` |
| Project create | 10.173 s |
| Unchanged refresh | 5.423 s; 0 parsed story sources |

Readable examples include `gen` → `Gene points`, `loi_rom` → `Lois romance`, `lust` → `Lust`,
and `wanda_dom` → `Domination`.

The deterministic authority digest before and after enrichment was identical:

`7ed1a173bf4bb5b4f8570e677178e5bb086705543030c20d0fcb19df7e299e54`

The two inspected archives were fingerprinted before and after the final run and remained
byte/timestamp identical:

- `scripts.rpa`: 2,140,282 bytes; SHA-256
  `053abb13454180a2cf9b0aa762e33deda98cf027d9c1e39082f5795982720303`;
  LastWriteTimeUtc `2026-07-03T01:11:16Z`.
- `extras.rpa`: 38,708 bytes; SHA-256
  `53da12dd0437e981c9c702478b318cc0b6b0b08dbbc47f85b9dc0977456a7753`;
  LastWriteTimeUtc `2026-07-03T01:11:16Z`.

No other game archive or media payload was opened by the final M09 acceptance path. The game
folder was never written, Ren'Py/game Python was never executed, and cloud AI was not invoked.

## Windows acceptance evidence

All commands ran on Windows with CPython 3.12.10 from the repository virtual environment.

| Command | Exit | Result |
|---|---:|---|
| `.\.venv\Scripts\python.exe -m pytest -q` | 0 | 546 passed in 42.43 s |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | 0 | All checks passed |
| `.\.venv\Scripts\python.exe -m mypy --strict src\renpy_story_mapper` | 0 | 56 source files passed |
| `.\.venv\Scripts\python.exe -m pip check` | 0 | No broken requirements |
| `node --check` for all four packaged JavaScript modules | 0 | Passed |
| `git diff --check` and milestone-range diff check | 0 | Passed |
| `scripts\m09_metadata_acceptance.py --game-folder <MsDenvers game> --output-dir artifacts\M09\msdenvers-metadata-final` | 0 | Authority/archives unchanged; replay absent; metadata/search/refresh/integrity passed; 0 provider calls |
| `scripts\m08_browser_acceptance.py --output artifacts\M09\browser-acceptance-final-head` | 0 | Chrome 100% and 200%; no overflow; exact navigation/review/pagination passed; 0 provider constructions, starts, or remote requests |

At normal zoom the Chrome harness allocated 528 px to the map viewport and 158 px to the compact
organization panel. At 200% zoom the responsive layout had no horizontal overflow offenders.

## Independent review and corrections

The first independent review of `b789c61` correctly blocked shipment. It found that loose replay
sources could enter canonical analysis beside `scripts.rpa`, extracted titles lacked the exact key
needed for display, and enrichment was available only through legacy presentation APIs rather than
the shipped M07/M08 browser flow.

Corrections made `scripts.rpa` exact folder authority, added only provable literal title keys, and
projected the already-persisted metadata onto copied Route Map/Detail responses without changing
stored topology, authority hashes, or applied AI titles. The reviewer then found one final
inconsistency: duplicate title keys were last-wins in the browser. That lookup now uses the same
fail-closed suppression as legacy presentation.

The reviewer committed two adversarial tests as `30edada`, integrated as `82d777a`. Its final audit
of integrated head `6fdc2cc` independently reproduced duplicate suppression, ran 20 focused M09
tests, Ruff, and diff checks, reported no P0-P3 issue, and recommended shipment. The orchestrator
then independently reran the complete 546-test Windows suite and final Chrome harness.

## Limitations and deferred work

- This is intentionally not a general Python evaluator. Multiline or dynamic expressions outside
  the allowlist are skipped. Forty-four MsDenvers records remain bounded diagnostics rather than
  guessed metadata.
- The 13 MsDenvers memory titles are stored with provenance but are not applied to chronology when
  they lack an exact literal story-label key. M09 does not infer fuzzy title/scene matches.
- Exact title matching is case-sensitive and label-only. Conflicting keys fail closed.
- When `scripts.rpa` exists, loose developer overrides are intentionally ignored as story sources.
  Folders without `scripts.rpa` retain the earlier loose-source behavior.
- Browser enrichment opens one additional local project connection for an enriched response and
  caps synthesized dialogue rows at 100. It remains local and provider-free.
- A prior diagnostic attempt showed that full real-project route classification can take more than
  two minutes on this canonical-scale project. M09 does not claim to solve that pre-existing route
  query performance issue; its metadata create/search/refresh acceptance passed independently.
- Media thumbnails, image/audio ingestion, AI story organization, LM Studio, hosted deployment,
  installers, and replay chronology remain outside M09.

## Commit and worker summary

- Milestone bootstrap/docs: `b448b3b`, `a598363`.
- Initial integrated metadata implementation: `8409764`, `bbf1f7d`, `b789c61`.
- Exact source-authority/title correction: worker `c272402`, integrated `fc208eb`.
- Shipped-browser enrichment: worker `865ea2b`, integrated `d58912a`.
- Independent adversarial tests: worker `30edada`, integrated `82d777a`.
- Duplicate-title fail-closed correction: worker `828d43e`, integrated `6fdc2cc`.

## Required artifacts

- `docs/milestones/M09/GOAL.md`
- `docs/milestones/M09/TASKS.md`
- `docs/milestones/M09/COMPLETION_REPORT.md`
- `docs/milestones/M09/INFOGRAPHIC.png`
- Real read-only evidence: `artifacts/M09/msdenvers-metadata-final`
- Final Chrome evidence: `artifacts/M09/browser-acceptance-final-head`

The native infographic was generated with Codex's built-in image-generation tool and copied into
the milestone folder. Generated-image text can be imperfect; this Markdown report is the factual
authority for M09.
