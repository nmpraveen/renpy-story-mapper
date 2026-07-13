# M08 Completion Report - Web-Only AI Story Understanding Validation

Date: 2026-07-13

Branch: `codex/m08-web-ai-validation`

Baseline: `32e9a3c4a41c0eb4acc9b13af966f4b727319d46`

PR state: one M08 pull request will be opened and intentionally left unmerged.

## Outcome

M08 is complete. Ren'Py Story Mapper now ships one supported interface: the local loopback browser.
The obsolete standalone PySide6 graph product and its entry point are gone. After the deterministic
static analyzer maps factual control flow, a separately consented GPT-5.6 Luna High run may organize
bounded narrative scopes into a readable two-level AI Story Map. Technical Structure remains the
source of truth and fallback for every factual edge, gate, effect, merge, loop, ending, unresolved
record, and source line.

The milestone did more than demonstrate a happy path. Independent review found that the first
implementation accepted globally valid but group-wrong evidence, exposed an obsolete cloud-start
route, mixed run metrics with project history, and paged unrelated edges beside visible nodes. The
corrections now fail closed, invalidate unsafe pre-fix AI assemblies, and retain deterministic
fallback instead of presenting unsupported interpretation.

## Product flow delivered

1. The browser creates, opens, or refreshes a local `.rsmproj`; no provider is constructed.
2. Deterministic static analysis discovers source precedence, labels, choices, conditions, jumps,
   calls, returns, fallthrough, merges, loops, endings, requirements, effects, and evidence.
3. The user selects exact route scopes or visible nodes. A provider-free preview resolves bounded
   nodes, internal/boundary edges, evidence, facts, input hash, authority hash, model, and budget.
4. Only the strict nine-field, single-use consent payload may start cloud work. GPT-5.6 Luna, High
   reasoning, and fast mode disabled are locked by code.
5. Parallel workers persist each scope independently. Invalid, oversized, cancelled, or unsupported
   scopes stay technical; validated scopes require subject-owned evidence for every AI group member.
6. Review/apply/discard never changes deterministic authority. Accepted groups are projected into a
   quotient flowchart using only real deterministic cross-group edges.
7. The AI Story Map becomes the default reading view. Technical Structure remains one click away;
   Detail / Evidence exposes exact members, claims, gates/effects, and qualified source lines.
8. Opening, navigation, comparison, and unchanged replay make zero provider and remote calls.

## Major deliverables

- Browser-only wheel and launch documentation; no GUI console entry point or QGraphicsView product
  files remain.
- Checked-in deterministic/AI evaluation manifest, schema, rubric, synthetic fixtures, accepted and
  rejected candidates, comparison output, and provider-free acceptance runner.
- Exact bounded narrative windows with hard node/edge/evidence/fact/prompt limits, deterministic
  hashes, recovered-source acknowledgement, single-use consent, cancellation, resume, and cache.
- Deterministic AI Story Map projection with two public levels, real edge quotienting, technical
  fallback, exact evidence navigation, and stable coverage/projection hashes.
- Topology-complete AI pagination: each node slice carries only its real incident edges, dense edge
  sets use a slice-bound cursor, and off-page endpoints are explicit continuation portals.
- Honest current-run accounting distinct from explicitly labeled persisted project history.
- Strict evidence ownership in prompt/cache/validation/apply/overlay/AI-query boundaries. Empty
  claims, swapped evidence, cross-group facts, context/boundary-only support, and uncovered members
  are rejected.
- Warm paper-style browser flowchart with AI/technical comparison, search, pan/zoom/fit, keyboard
  navigation, exact consent, progress, coverage, review, apply, discard, and responsive 200% zoom.

## Corrected live Luna validation

The initial live candidates were rechecked after independent review. Three contained claims whose
evidence IDs existed in the request but belonged to a different group member. Those assemblies are
now rejected by the product and were not counted as accepted. The same previously approved bounded
selections were rerun through the corrected contract. No unrestricted MsDenvers run occurred.

| Source | Final scopes | Corrected live cloud work | Final unchanged replay | AI scope / technical coverage |
|---|---:|---:|---:|---:|
| Generated complex branching fixture | 51 validated, 2 deterministic fallback | 69 calls across bounded repair passes; 1,157,223 input / 46,170 output tokens | 0 calls; 0.163 s fresh, 0.176 s replay | 96.23% / 100% |
| Small real `.rpy` | 8 validated, 0 fallback | 17 calls across bounded repair passes; 262,529 input / 14,766 output tokens | 0 calls; 0.022 s fresh, 0.023 s replay | 100% / 100% |
| Small recovered `.rpyc` | 0 validated, 5 deterministic fallback | 0 calls / 0 tokens | 0 calls; 0.131 s fresh, 0.122 s replay | 0% / 100% |
| Four bounded MsDenvers windows | 1 validated, 3 deterministic fallback | 1 call; 16,982 input / 956 output tokens | 0 calls; 1.253 s fresh, 1.243 s replay | 25% / 100% |

Corrected-contract cloud usage was 87 calls, 1,436,734 input tokens, and 61,892 output tokens.
Including the earlier candidates that the new review rule invalidated, the four project attempt
ledgers contain 167 calls, 2,677,542 input tokens, and 113,152 output tokens. This distinction is
intentional: rejected experiments are not erased from accounting.

Final evidence-backed organization and projection metrics:

| Source | AI groups / claims | Authoritative nodes -> projected | AI-owned / fallback route nodes | Projection hash |
|---|---:|---:|---:|---|
| Complex fixture | 58 / 85 | 102 -> 68 | 92 / 10 | `810aaa172f9950ef0fb72bd685ebe424879c0346471a81693a3e1fb6e89fd2da` |
| Small `.rpy` | 9 / 20 | 20 -> 9 | 20 / 0 | `3f516639d2c8ee971a571b4cda28c465eafaa05cbf25072b1ee2e6e7f7946d40` |
| Small recovered `.rpyc` | 0 / 0 | 14 -> 14 | 0 / 14 | `0412788ebc6554113300200374c3ebca75b0260815378d9b08ec00f79fe0801e` |
| Bounded MsDenvers | 1 / 1 | 579 -> 568 | 12 / 567 | `4efa945d9a35c8510d07a3bc4cc48205a48fe449ad402f17927881cff6816bfd` |

Authority hashes remained unchanged before/after every corrected run:

- Complex: `fbd7a32700ee04d666578ef4dd61f55e005ba1112234d727cdc54f2e40cc1524`
- Small `.rpy`: `7119534e0d56a122401ec196ab7f03f125ce8de113def98fe243c3199169c2ef`
- Small recovered `.rpyc`: `1345ad101e47c45909a154abd761898a1c4b8ba491412a737567dff71db106cb`
- MsDenvers: `d070c6b1892d4dcc3554debc8ac0f35cd5d385f9873414dadcd954107712c2ef`

## Windows acceptance evidence

All commands ran on Windows with the repository CPython 3.12 virtual environment.

| Command | Exit | Result |
|---|---:|---|
| `.\.venv\Scripts\python.exe -m pytest -q` | 0 | 524 passed in 41.29 s |
| `.\.venv\Scripts\python.exe -m ruff check .` | 0 | All checks passed |
| `.\.venv\Scripts\python.exe -m mypy --strict src/renpy_story_mapper` | 0 | 55 source files passed |
| `.\.venv\Scripts\python.exe -m pip check` | 0 | No broken requirements |
| `node --check` for every packaged JavaScript module | 0 | Passed |
| `git diff --check` | 0 | Passed; only Windows line-ending notices |
| `scripts\m08_non_live_acceptance.py --output-dir artifacts\M08\non-live-final-corrected` | 0 | Fresh/repeated accepted; forbidden global scope rejected; replay 0 calls |
| `scripts\m08_browser_acceptance.py --output artifacts\M08\browser-final-corrected` | 0 | Chrome 100% and 200%; exact consent, pagination, evidence, keyboard, review/apply/discard; no overflow; 0 provider constructions/starts/remote requests |
| `pip wheel . --no-deps --wheel-dir artifacts\M08\dist-final-corrected` | 0 | Wheel built and inspected |

Wheel: `renpy_story_mapper-0.1.0-py3-none-any.whl`

SHA-256: `f3d59e1b6adf8499746b925c2afa3cc676e09df7fbbf7324b6bd46cb505d24a4`

Entries: 80. Desktop/GUI/QGraphics matches: zero. Console scripts: only
`renpy-story-mapper` and `renpy-story-mapper-web`.

Read-only inputs were fingerprinted again after all processing and remained byte-identical:

- `script small new.rpy`: 9,994 bytes; SHA-256
  `d3a4e0a305c6c8a8d84ff5bd99845a4035f0bde7ce953699af71d607806d7f71`;
  LastWriteTimeUtc `2026-03-27T22:21:22Z`.
- `script smaller version.rpyc`: 30,533 bytes; SHA-256
  `0ae658c6617c119abe5e65c00e34bf6c79c213e5b6a466a00ff2e9bbdb1a3ddc`;
  LastWriteTimeUtc `2026-05-23T06:19:06Z`.
- MsDenvers `scripts.rpa`: 2,140,282 bytes; SHA-256
  `053abb13454180a2cf9b0aa762e33deda98cf027d9c1e39082f5795982720303`;
  LastWriteTimeUtc `2026-07-03T01:11:16Z`.
- The canonical Dropbox `scripts.rpa` was not accessed in M08.

## Independent review and corrections

Initial independent review at `8ebb0ae` ran 510 tests and reported no P0, three P1, and two P2
findings. All were corrected:

1. Superseded `/api/v1/organization/*` endpoints now return 404 and cannot construct a provider.
2. Every validated group requires nonempty, member-owned evidence; apply, route overlay, and direct
   AI Story Map query revalidate persisted assemblies and reject unsafe pre-fix data.
3. Required completion artifacts are present.
4. Current-run scope/call/token/time/cache metrics are exact to the selected run; reopened cumulative
   data is explicitly labeled persisted project history.
5. AI pages return complete bounded incident topology with cursor-bound dense-edge continuation.

Final independent re-review at `1bdb295` closed all five prior findings and reported no unresolved
P0, P1, or P2 issue. The reviewer independently reproduced 14 focused corrective tests and the full
524-test suite, Ruff, strict mypy across 55 source files, `pip check`, all four JavaScript syntax
checks, both milestone-range `git diff --check` commands, provider-free fresh/replay acceptance, the
real Chrome harness at 100% and 200%, and browser-only wheel inspection. The reviewer recorded zero
provider constructions, starts, remote requests, and replay calls, then recommended opening the
unmerged M08 PR. Live Luna metrics and external samples were intentionally not rerun during this
read-only review.

## Limitations and deferred work

- AI organization is required for the finished reading experience, but it is not deterministic
  authority. If consent is withheld or validation fails, the local technical map remains complete.
- The complex fixture reaches 96.23% AI scope coverage, not 100%; two no-op/technical scopes are
  intentionally fallback. Some accepted titles remain close to source labels instead of polished
  prose, so editable naming remains useful.
- The small recovered `.rpyc` is technically complete but has no accepted AI scopes. Recovered
  source provenance and deterministic mapping work; narrative enrichment needs evidence-bearing
  scope improvements rather than relaxed validation.
- Three MsDenvers windows exceed the 48,000-character evidence-complete prompt bound and therefore
  fall back before cloud transmission. The one accepted bounded group is structurally grounded but
  narratively generic (`Sequential milestone chain`). M08 does not claim full-game understanding.
- The official walkthrough was diagnostic evaluation evidence only. It is not committed and is not
  required by the product.
- Current-run accounting identity lives in browser-session memory. Reopening intentionally shows
  labeled project-history totals because the attempt schema has no persisted run ID.
- The product is local-loopback browser software, not a hosted web service or standalone executable.
  LM Studio, packaging/installers, hosted deployment, macOS work, and unrestricted full-game AI are
  deferred.
- Static source recovery never executes Ren'Py/game Python. Reconstructed `.rpyc` physical lines are
  qualified recovery evidence, not original developer-source line authority.

## Commit summary

Implementation, integration, documentation, and independent review are represented by the milestone
range `32e9a3c4a41c0eb4acc9b13af966f4b727319d46..1bdb295`, including browser-only cleanup,
evaluation, bounded windows, web consent, projection, browser experience, evidence ownership,
topology paging, honest accounting, final browser evidence fixtures, the native infographic, and
the completed corrective re-review.

## Required artifacts

- `docs/milestones/M08/GOAL.md`
- `docs/milestones/M08/TASKS.md`
- `docs/milestones/M08/EVALUATION_CORE.md`
- `docs/milestones/M08/BROWSER_EXPERIENCE.md`
- `docs/milestones/M08/COMPLETION_REPORT.md`
- `docs/milestones/M08/INFOGRAPHIC.png`
- Provider-free acceptance: `artifacts/M08/non-live-final-corrected`
- Real Chrome acceptance: `artifacts/M08/browser-final-corrected`
- Corrected live evidence: `artifacts/M08/live/*-corrected-*.json`
- Final wheel: `artifacts/M08/dist-final-corrected`

Generated-image text can be imperfect. This Markdown report is the factual authority for M08.
