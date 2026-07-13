# M07.1 Completion Report — Safety and Real-Project Closure

Date: 2026-07-12  
Branch: `codex/m07-1-safety-real-project-closure`  
Baseline: `4c421a10364d2c75d8437b2775cbb57ef28d80fc`  
Status: Complete; one pull request remains intentionally unmerged.

Pull request: `#12` — `https://github.com/nmpraveen/renpy-story-mapper/pull/12`.

## Outcome

M07.1 closes the correctness, privacy, and real-browser gaps found after M07 without changing the
product's deterministic authority. Recovered source is blocked from cloud transmission unless the
exact run has a persisted acknowledgement. Consent, scopes, generation, provider budgets, and each
provider attempt are bound and checked fail-closed. The browser now uses real project data for
qualified evidence, arbitrary route lanes, page continuations, draft review, and refresh status.

No live AI provider, remote endpoint, canonical archive, or embedded Ren'Py/game Python was used in
acceptance.

## Delivered behavior

- Exact normal and repair prompt measurement and deterministic partitioning below 48,000
  characters.
- Conservative default provider envelope: 48 hard calls; 600/900 soft/hard seconds; 1,500,000/
  2,000,000 soft/hard tokens. Per-attempt admission includes prompt bytes, a bounded output, and a
  conservative provider-overhead reservation.
- Single-use consent bound to the exact generation and prepared scope set, plus recovered-source
  acknowledgement checks at prepare time and immediately before every initial or repair
  transmission.
- Fail-closed accounting for missing, negative, malformed, unreserved, and over-ceiling provider
  usage. Invalid counts cannot reduce totals, replenish admission, or be persisted as valid usage.
- Generation-safe drafts, accepted overlays, corrections, pins, claims, discard, and refresh
  invalidation. Stale organization cannot overwrite refreshed deterministic analysis.
- Real qualified evidence paths, exact line ranges, physical/reconstructed line-basis labels, and
  source derivation provenance in Detail / Evidence.
- Data-driven lane geometry for arbitrary lanes, plus truthful forks, merges, loops, terminals,
  gates, and cross-page continuation portals.
- Honest asynchronous refresh polling and persisted draft discard.
- Production mock-project mode removed. The acceptance harness drives real Chrome through an
  ephemeral loopback `LocalWebServer`, real `ProjectApi`, and a temporary SQLite `.rsmproj`.

## Worker tasks and integration

The permanent orchestrator reviewed and integrated every worker diff. Full task IDs, branches,
responsibilities, and commit mappings are recorded in `TASKS.md`.

- Cloud safety/provider boundaries: `0656c39`.
- Backend lifecycle and API: `a839d8f` through `f4e58f6`.
- Route map/live browser: `bcf8ce0` through `15e78ba`.
- First independent review regression evidence: `a8fdbd0`.
- Review corrections: `66e7d0a`, `6839f9a`, `9526b1e`.
- Negative-accounting regression and closure: `757d9c4`, `c889fdd`, `7012482`.
- Qualified browser evidence rendering: `d46767a`.
- Final static asset manifest: `3399154`.

The final independent Sol 5.6 High audit ran against `d46767a`: 29 focused tests passed, the live
Chrome harness passed at 100% and 200%, qualified paths rendered with no `source unavailable`, and
the reviewer reported no unresolved P0–P2 findings. The later `3399154` commit changes only the
deterministic hash for the already-reviewed `app.js` asset.

## Windows acceptance evidence

Runtime authority: Windows CPython 3.12 from `.venv\Scripts\python.exe`.

| Check | Exact result |
|---|---|
| `python -m pytest -q` | Exit 0; **497 passed in 38.35s** |
| `python -m ruff check src tests scripts --no-cache` | Exit 0; all checks passed |
| `python -m mypy --strict src\renpy_story_mapper` | Exit 0; no issues in 54 source files |
| `python -m pip check` | Exit 0; no broken requirements |
| `git diff --check` | Exit 0 |
| `node --check` for `api.js`, `app.js`, `contract.js`, `graph.js` | All exit 0 |
| `scripts\m07_browser_acceptance.py` | Exit 0 at 100% and 200% |
| Wheel build and inspection | Exit 0; 79 entries, required web assets present, zero mock/sample entries |

The first loaded full-suite run exposed the existing M06 two-second scale assertion at 2.18s. Three
isolated repetitions passed at 1.78s, 1.85s, and 1.86s; the final complete suite passed. A later
full-suite run also correctly caught the changed `app.js` manifest hash; the manifest was refreshed
and its focused test passed before the final 497-test run.

### Browser metrics

- 17 deterministic lanes.
- 57 rendered route items.
- 10 cross-page continuation portals.
- 4 exact evidence records in the exercised detail view.
- 16 loopback requests at each zoom.
- 0 provider constructions, 0 remote requests, and no horizontal document overflow.
- 100% route screenshot SHA-256:
  `06e8dc1938229c97aab1764171c2c4decd801568a27a11b71bd4760f4ce37bed`.
- 200% route screenshot SHA-256:
  `fb075b025d6ed4f4d314e03d425f32f3e1c30539a459afeeb3a817332ae6295f`.
- 100% qualified-detail screenshot SHA-256:
  `399bfd4844169db685d80687d2aded2c2cdf0f0c6480d020a72ac4092e93d564`.

Browser evidence is stored under `artifacts/M07.1/browser-accepted-head`.

### Wheel evidence

Artifact: `artifacts/M07.1/wheel-accepted/renpy_story_mapper-0.1.0-py3-none-any.whl`  
SHA-256: `96311d0342b30d30fb63299b0d7e7e6d6fb3b066508ce0c538bb2d178dfe6f28`.

## Canonical sample and privacy

The canonical `scripts.rpa` archive was not accessed, so no before/after fingerprint was required.
Acceptance used only repository fixtures and temporary generated projects. No story text was sent
to a provider; cloud and remote calls were trapped and remained at zero.

## Limitations and deferred work

- The conservative per-attempt token ceiling depends on the configured 16,384-token provider
  overhead allowance; a provider reporting more fails closed after the attempt and preserves the
  charged overage.
- Dense maps remain horizontally pannable by design. At 200% zoom, the lane legend precedes the
  canvas vertically; keyboard controls, fit, and bounded paging remain available.
- The pre-existing M06 scale test uses a strict two-second wall-clock assertion and is sensitive to
  concurrent machine load even though the final suite passed.
- Consent is intentionally single-use. Some rejected pre-start operations may require obtaining a
  fresh token rather than reusing the rejected token.
- No full-game Luna rerun, LM Studio integration, installer, hosted service, analyzer rewrite,
  legacy desktop removal, or source-recovery expansion was attempted.

## What is possible next

The project can now validate the real local web product safely: ingest static Ren'Py sources,
display a two-level route map with exact evidence, optionally organize bounded acknowledged scopes,
review/apply/discard candidates, refresh deterministic analysis, and resume work without silently
crossing privacy, generation, or budget boundaries. Any next milestone requires explicit approval.

## Native infographic

`INFOGRAPHIC.png` was generated with Codex's native image-generation capability from the verified
facts in this report. SHA-256:
`15502175faa9c879f68d0f649ce56d6462a23be83d6c21fe22d800f1d777b078`.

The generated image is a visual summary; this Markdown report remains the factual authority.
