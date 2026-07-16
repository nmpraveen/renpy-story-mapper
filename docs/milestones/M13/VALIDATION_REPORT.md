# M13 validation report

Status: Verification in progress; provider-free product acceptance passed

Baseline: `f67df8a7cb805bf4adf8590585bae700d2f3117f`

Validated product commit: `859328e1cbe8933809bd49001d681d1f7f6701d4`

Validation date: 2026-07-16

## Acceptance matrix

| Criteria | Result | Durable evidence |
|---|---|---|
| 1-5 | Pass | Stable logical/input/cache identities, exact authority binding, deterministic E/C handle maps, content-addressed claims, claim-local validation, deterministic-title fallback, one-repair maximum, and partial-salvage tests |
| 6-9 | Pass | Independent batch-item commit/retry/split tests, durable queue/cache/attempt records, cancellation preservation, deterministic recursive segments, lazy bounded claim-DAG resolution, and linear-growth assertions |
| 10-13 | Pass | Bounded chapter/route/ending/plot/character fan-in, exact M12 leaf semantics, separated persistent routes, contextual contradiction identity, factual conflict salvage, and interpretive review warnings |
| 14-16 | Pass in mocked/provider-free acceptance | Provider-independent boundary, sterile structured Codex CLI adapter, runtime requested/resolved identity, no fallback, consent/budget/timeout/cancellation tests, versioned prompts, sanitized storage, and raw-debug-off defaults |
| 17-18 | Pass | Real Chrome at 100% and 200%, optional Narrative overlay, two semantic levels, lazy citations, job drawer, deterministic-title restoration, zero-call replay; optional weak-boundary overlays intentionally deferred |
| 19 | Pass | Complete current private-corpus provider-free simulation: 1,812 scenes, batching, hierarchy, retries, partial publication, cancellation, invalidation, exact cache replay, route separation, and linear storage/provenance growth |
| 20 | Pending exact consent | Representative live manifest prepared without transmission; `provider_submit_calls` is zero. Exact manifest-bound confirmation is required before the bounded live run |
| 21 | Pass for provider-free/private/browser runs | Source/archive and M10/M11/M12 authority snapshots unchanged; zero Ren'Py/game/creator/runtime execution; no unauthorized remote request |
| 22 | Partially pass | Release suite and browser/private/package checks pass. A separately configured external-model review remains pending explicit informed approval to transmit private repository code |
| 23 | In progress | Reports, validated product commit, and native infographic are durable. Independent review, final live evidence, and PR-readiness reconciliation remain |

## Commands and results

| Command / check | Result | Artifact or notes |
|---|---|---|
| Focused M13 validation, contradiction, hierarchy, reduction, pipeline, provider, and API tests | 62 passed | Final authority/contradiction corrections at validated product commit |
| `.\scripts\validate.ps1 -Tier Release -Python 'C:\Users\prave\AppData\Local\Programs\Python\Python312\python.exe'` | 951 passed, 7 deselected in 179.16 seconds; total 194.7 seconds | Ruff passed; strict mypy passed across 91 source files; `pip check`, JavaScript checks, whitespace, isolated sdist/wheel build, install/import, assets, and notices passed |
| `scripts/m13_provider_free_acceptance.py` against the accepted current private project | Passed | `tmp/m13-provider-free-private-reviewed/acceptance.json`, SHA-256 `351b952e5f7dba443190202fa2461b3f41f3b70e2870dbbc9ff9820f7f095279` |
| `scripts/m13_browser_acceptance.py` | Passed at 100% and 200% Chrome zoom | `tmp/m13-browser-acceptance-reviewed/acceptance.json`, SHA-256 `2b938d37b152456cf3646f23ebda98d73ccc79c79379394ec35aa4df01a88273` |
| `scripts/m13_live_acceptance.py` preview | Prepared; no submission | `tmp/m13-live-provider-acceptance/consent-preview.json`, SHA-256 `50fe3389870e568a409f0cb9de13fc8f12dfc75e1c6636c5982e64396ba085e9` |
| Native image generation | Complete | `INFOGRAPHIC.png`, 1,619,429 bytes, SHA-256 `7ac430f485f26956b271268ad8c6f63cd6d403e8570d837d2cd1f28123c98d3d` |
| `git diff --check f67df8a7..859328e` | Passed | No whitespace errors |

## Private provider-free acceptance

- The accepted project contained 1,812 scenes, 9,120 atoms, one chapter, 13 lanes, 102 temporary
  branches, and five occurrences.
- The complete hierarchy estimated 2,590 logical jobs. It published 1,812 scene, 354 segment, 323
  chapter, 12 route, 43 ending, 32 character, and one route-aware plot artifact.
- All 2,568 factual claims had owned evidence. The report published 2,600 claims with zero unknown
  or out-of-scope references and zero claim-DAG cycles.
- The fault matrix covered malformed items, transient failure, provider/content refusal, batch
  splitting, partial claim publication, cancellation after 16 validated scenes, identity
  invalidation, and preservation of prior accepted artifacts.
- Exact cache replay succeeded with zero simulated provider calls. Serialized M13 state was
  18,007,124 bytes, with approximately linear artifact and provenance growth.
- The accepted baseline project remained SHA-256
  `b0362db6be0a885936bfe7053917aa49812dd55ed9ea47c6f63da11a72b6bf07`.
  Private `scripts.rpa` and `extras.rpa` remained unchanged at
  `053abb13454180a2cf9b0aa762e33deda98cf027d9c1e39082f5795982720303` and
  `53da12dd0437e981c9c702478b318cc0b6b0b08dbbc47f85b9dc0977456a7753`.
- Network, remote-provider, subprocess, Ren'Py/game/creator-code, and runtime-tracing counters were
  zero. Raw debug payload retention was false, and no private path was recorded.

## Browser acceptance

- Chrome passed at 1440x900/100% and effective 720x450/200%, without horizontal overflow,
  browser errors, or remote requests.
- Cloud AI and the Narrative overlay were off by default. The consent card showed provider/model,
  exact selected scope, fact-only mode, 87 logical jobs, estimated calls and tokens, hard limits,
  and M12 inclusion before any run could be submitted.
- The production workflow published 27/27 scene artifacts and the full hierarchy through a
  structured offline provider. Detail/Evidence lazily resolved both scene and plot citations.
- Turning Narrative off restored the deterministic M11 title. Exact replay reported zero provider
  calls at both zoom levels. Source, authority, M12, and packaged static-asset snapshots were
  unchanged.

## Live manifest awaiting consent

The preview is bound to preparation
`m13_preparation_5119c7f7d4333738b432ac46cb90b240730ea392ca3fd4dba5490e8141b354ab`
and consent manifest
`m13_consent_3bb95e7426f079172fb8e99e25485a2820a41d05f717a16dc103e037bac67cf3`.
It selects a synthetic 27-scene fact-only sample covering common spine, temporary branch,
persistent routes, occurrences, loop context, 14 endings, one M12 result, four exact prerequisite
strings, and one complete route-aware reduction. The conservative estimate is 87 logical jobs,
63 provider calls, 324,994 input tokens, and 81,600 output tokens. Hard limits are 80 calls,
400,000 input tokens, 150,000 output tokens, 550,000 total tokens, 1,800 seconds, and concurrency
one. Reliable price data is unavailable, so no monetary limit is represented as known. No provider
submission has occurred.

## Review findings and dispositions

- P1: publication originally did not apply contextual contradiction salvage. Fixed in `859328e`;
  later same-context factual conflicts are omitted claim-locally, while interpretive disagreements
  remain visible review warnings.
- P1: a large exact M12 citation could exceed Detail/Evidence response bounds. Fixed in `859328e`
  with a deterministic hash-bound bounded projection and lazy authority resolution.
- P1: exact M12 authority language needed stronger semantic preservation. Fixed in `859328e` by
  requiring hierarchy factual claims to copy one exact M12 leaf's text and normalized semantics;
  AI interpretation remains separately labeled.
- No unresolved P0 or P1 finding remains from the integrated primary adversarial pass. This is not
  represented as the contract's separately configured independent review.

## Remaining gates and limitations

- Live provider acceptance remains blocked on exact user confirmation of the prepared manifest.
  The preview itself proves zero submission.
- A separate read-only review was prepared with explicit `gpt-5.6-sol`, high reasoning, fast mode
  disabled, and an inner read-only sandbox. It was rejected before transmission because it would
  send private repository code to an external model service. No review data left the machine, and
  the review remains pending explicit informed approval rather than being routed around the
  safeguard.
- The validator supports zero or one targeted claim/schema repair. The integrated scheduler
  normally performs claim-local salvage and independent item retry; it does not issue a repair call
  merely because repair is permitted.
- Weak-boundary suggestions, LM Studio/local-provider support, and export polish are intentionally
  deferred optional work. Bounded character participation and route-aware interpretations are
  included.
