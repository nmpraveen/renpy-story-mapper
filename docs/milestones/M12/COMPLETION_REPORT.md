# M12 completion report

Status: PR ready

Validated product commit: `1df83098872fb63d434ff3e59a79e0f286944260`

Pull request: [PR #22](https://github.com/nmpraveen/renpy-story-mapper/pull/22), open and unmerged

## Outcome

M12 implements an on-demand, deterministic, bounded, cacheable static route solver over exact
M10/M11 authority. From an authoritative entry or explicit supported starting context, the
browser can select supported destinations and present ordered human scenes, visible choices,
templated instructions, exact prerequisite/effect attribution, persistent commitments,
conservative uncertainty, alternatives, expandable evidence, safe cancellation, cache replay,
and versioned JSON export without executing Ren'Py, the game, creator code, a provider, or a
remote request.

## Acceptance evidence

| Criterion | Result | Evidence |
|---|---|---|
| 1-4 | Pass | Exact authority/request identity, authoritative starts, destination catalog, selected occurrences, normalized replay in focused tests and `VALIDATION_REPORT.md` |
| 5-11 | Pass | State identity, initialization, chronology, numeric thresholds, internal prerequisite ranking, call context, and loop safety fixtures |
| 12-16 | Pass | Versioned deterministic limits, byte-identical scale runs, conservative statuses, atomic persistence, cache/failure/cancellation tests |
| 17-18 | Pass | Real-browser 100%/200% workflow, four badges, two levels, exact evidence, cache replay, cancellation, deterministic export |
| 19 | Pass | 97 focused M12 tests plus separately executed browser acceptance and the complete amended direct-test matrix |
| 20 | Pass | Fast, Focused, Release, scale, browser, persistence/fault, real private acceptance, input immutability, zero-execution counters, and final reviews |

## Validation

| Command / review | Result | Artifact or notes |
|---|---|---|
| Fast | Pass; 39 tests | Ruff passed |
| Focused | Pass; 97 tests, 1 opt-in browser skip | All 12 `test_m12*.py` files; browser run separately |
| Release | Pass; 762 tests, 6 hardware-sensitive deselected | Ruff, strict mypy, dependency, JS, whitespace, build/install/import/assets all passed |
| Scale | Pass | Two byte-identical reports, SHA-256 `97f5194e6a2264d8006126f87088c13bb6dd3891cf217d8c76f5a2b0f1f2fcbc` |
| Browser | Pass | Report SHA-256 `0256aeefd8b34df69c3da7b1fcc91009c01b98b7ce516e6847dfea80a58c4207` |
| Persistence/fault/private harness tests | Pass; 32 tests | Atomicity, isolation, cancellation, emergency behavior, private boundaries |
| Emergency replay | Pass; 10/10 | Uncached abort, no normalized result, prior cache preserved |
| Real private acceptance | Pass | Five selected targets; report SHA-256 `194551a06be474bfaec41f6e5f01a75c6d0240b02cfa6d28c296dc50791d892e` |
| Final semantic review | Pass | Exact baseline through `1df83098872fb63d434ff3e59a79e0f286944260`; no semantic finding |
| Final delivery review | Pass | Same exact range; no product, correctness, security, UI, or delivery finding |

## Review findings

- Safe cancellation: final delivery review identified a result-publication race. Resolved in
  `ea52f92`; both browser zoom runs now cancel with a null result and usable Retry.
- Requirement chronology: final semantic review identified loss of an earlier entry assumption
  after a possible write and repeated gate. Resolved in `5faa12a` with exact chronological
  attributions and a deterministic regression.
- External-precondition ranking: adversarial review identified repeated uses of one starting
  assumption being overcounted. Resolved in `1df8309`; distinct assumptions rank once, the
  shorter equal-assumption route wins, one start instruction is rendered, and ordered repeated
  scene/choice/repeat evidence remains intact.
- Browser integrity: an intermediate Release run identified the pre-fix `app.js` hash in the
  asset manifest. Resolved in `69c1928`; the final Release run passed.
- Both final independent reviews returned `PASS`. No accepted or unresolved blocking finding
  remains.

## Integration and PR state

- Integrated diff reviewed against contract and exclusions: Yes
- Required checks passed: Yes
- Blocking findings resolved or explicitly accepted: Yes
- PR genuinely ready: Yes

## Remaining limitations

- M10 authority does not establish every variable's scope/default/persistent initialization.
  M12 remains unknown or uses an explicit external precondition rather than inventing state.
- Private terminal and persistent-lane destinations remain dynamic/unknown where M10 does not
  provide closed-world evidence.
- Optional thin Markdown output was omitted; deterministic JSON and the browser presentation are
  complete.
- Task controls did not expose verifiable model/reasoning/fast-mode selectors. No model-selection
  product logic was added.

The approval-gated PR exists, its URL and evidence are durable, and the repository lifecycle is
`PR ready`. Repository `Complete` remains reserved for reconciliation after the user merges it.
