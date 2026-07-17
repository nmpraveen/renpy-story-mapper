# M13 validation report

Status: Verification in progress; fresh local gates pass and the one approved public-synthetic canary failed

Baseline: `f67df8a7cb805bf4adf8590585bae700d2f3117f`

Runtime freeze: `edf80ed233799d2b61fec17a775187711a899cad`

Validation date: 2026-07-16

## Narrow-recovery local gates at `edf80ed`

| Command / check | Result | Artifact or notes |
|---|---|---|
| Combined Task A/Task B focused set | 155 passed in 74.83 seconds | Targeted Ruff and strict mypy over eight source/script files also passed |
| `powershell -ExecutionPolicy Bypass -File .\scripts\validate.ps1 -Tier Release` | Runtime/build gates passed; pytest 1,005 passed, 7 deselected, with one evidence-only lifecycle-line failure | The exact failed workflow-contract test passed after canonicalizing `Status: Integration.`; runtime freeze did not change and Release was not repeated |
| `scripts/m13_provider_free_acceptance.py --minimum-scenes 1812` with the exact prior private inputs | Passed once | `tmp/m13-provider-free-private-edf80ed/acceptance.json`; SHA-256 `82663e94c4763c0de14c86e45427b1469ffc29ae98486d2d6cee86b40fee1f4e`; zero-call replay |
| Browser worker `019f6d76-c028-7e71-b98a-0f8068fa56b4` | Passed once in 22.129 seconds | Chrome 100%/200%; report SHA-256 `8d065d7a34521dc834e115d053e2a6a2ab72910532e7bd7d662ef93031f81b02`; zero remote requests |
| Zero-submit live preview | Passed once in 1.256 seconds | Preview SHA-256 `abf81bc760b751d845c198a19b37e1ad2544a7f8df8a9dc00203584105ebd034`; preparation `m13_preparation_a9d419...`; consent `m13_consent_455142...`; provider submits zero |
| Public-synthetic schema-canary preview | Passed locally; zero calls | `tmp/m13-schema-canary-preview-edf80ed.json`; SHA-256 `64317773cbfb1ab524be41b8115e6bf7e3e59219e5960443f61de2c9a922a678`; used for the exactly approved execution below |
| Exactly approved public-synthetic schema canary | Failed once in 13.139 seconds; exit 1; no retry | Exactly one provider call; schema v3/provider v2, `gpt-5.6-sol`, reasoning `high`, `fast_mode=false`, timeout 120; provider response omitted resolved model identity; usage unavailable; sanitized result `tmp/m13-schema-canary-execution-edf80ed/result.json`, SHA-256 `fb905051c2d3ec6902e9dd6ea5432468e2fb72e7d6f351b77aa4307ee44af9a7`; stdout `e3b0c442...b855`, stderr `6d18ae7c...95eb` |

The fresh live preview binds adapter `m13-codex-cli-adapter-v2`, response schema
`m13-narrative-batch-response-v3`, prompt v4, model `gpt-5.6-sol`, reasoning `high`,
`fast_mode=false`, fact-only mode, M12 inclusion, 87 logical jobs, 63 estimated calls, and the
contract limits. The canary transmitted only the approved public-synthetic fact, "A blue circle is
round." No story/private content was sent. No live story-provider or external review call has been
made in this recovery pass.

## Historical `e0fd3bf` acceptance matrix

| Criteria | Result | Durable evidence |
|---|---|---|
| 1-5 | Local pass; independent closure incomplete | 70 focused tests and 966/7 Release at `e0fd3bf`; `CORRECTIVE_REREVIEW_REPORT.md` records the prior-freeze FAIL and single correction |
| 6-13 | Pass locally | Release plus 1,812-scene provider-free acceptance; exact authority, bounds, route/time context, claim DAG, and hierarchy checks |
| 14-16 | Provider-free pass; live blocked | Provider boundary and privacy checks pass locally; live run failed with only sanitized transient errors and exposed unstable consent-manifest identity |
| 17-18 | Pass | Chrome at 100%/200%, zero remote requests/errors/overflow and zero-call simulator replay; weak-boundary overlay deferred by contract |
| 19 | Pass | Full current private shape, faults, cancellation, invalidation, route separation, linear storage, and zero-call replay |
| 20 | Fail/incomplete | One exactly approved live run produced no artifacts and no replay; `LIVE_ACCEPTANCE_FAILURE.md` |
| 21 | Pass for local/private/browser; live incomplete | Private inputs and deterministic authority unchanged in completed gates; live sample source retained unchanged |
| 22 | Partial | Focused/Release/package/browser/privacy/private gates pass; no independent PASS at final head; live gate fails |
| 23 | In progress | Exact evidence and limitations are durable; active native goal retained; no PR created |

## Exact commands and results

| Command / check | Result | Artifact or notes |
|---|---|---|
| Focused M13 authority/reduction/validation set | 70 passed in 37.65 seconds | Includes inherited route/time scope, mandatory-authority bounds, duplicate representations, and exact proxy scope |
| `powershell -ExecutionPolicy Bypass -File .\scripts\validate.ps1 -Tier Release` | Passed at `e0fd3bf`: 966 passed, 7 deselected in 178.22 seconds | Ruff; strict mypy over 91 files; `pip check`; four JavaScript checks; whitespace; isolated sdist/wheel build, install, import, assets, and notices all passed |
| `scripts/m13_provider_free_acceptance.py --minimum-scenes 1812` against the accepted private project | Passed | `tmp/m13-provider-free-private-e0fd3bf/acceptance.json`; SHA-256 `31f91a5704dc221018ea955af7beef33cdd9425a39c9d2777ef22ff11b4dd114` |
| `scripts/m13_browser_acceptance.py --output-dir tmp/m13-parallel-browser-e0fd3bf/worker-019f6d0f-b146-7f12-9294-3af8f7bc0bc7` | Passed once, 23.194 seconds | 100%/200%; report SHA-256 `dd873f0fcaa6532c317fef982a366b94151864052d27458c45803dddf7691437` |
| `scripts/m13_live_acceptance.py` preview for `gpt-5.6-sol` | Prepared with zero submissions | Preparation `m13_preparation_f331d17b9e6bc8f3a476a2166c74a4fd8092d9b2fecc20f920fd5858080c4dc6`; preview SHA-256 `406ee106aa7f1bc68001d49c928856963ff67e3cdd6916270d19283285f38fb6` |
| Same live command with exact `--confirm-preparation-id` after two explicit approvals | Failed, exit 1, about 37 seconds | 74 failed jobs; 222 transient attempts; 24 provider calls; zero tokens; no artifacts; replay not reached |
| Native image generation | Complete | `INFOGRAPHIC.png`; SHA-256 `7ac430f485f26956b271268ad8c6f63cd6d403e8570d837d2cd1f28123c98d3d` |

The first live command request was policy-rejected before process launch and made zero provider
calls. After the user explicitly approved external transmission of the synthetic repository-derived
facts, the unchanged command launched once. No retry followed its runtime failure.

## Final-head provider-free/private evidence

- Corpus: 1,812 scenes, 9,120 atoms, one chapter, 13 lanes, 102 temporary branches, and five
  occurrences.
- Full hierarchy: 2,590 logical jobs; 1,812 scene, 354 segment, 323 chapter, 12 route, 43 ending,
  32 character, and one plot artifact.
- Claims: 2,600 published; 2,568 factual; all factual claims owned evidence; zero unknown/out-of-
  scope references and zero DAG cycles.
- Fault matrix: batch refusal/split, malformed and transient retry, content refusal recovery,
  partial publication, cancellation after 16 scenes, identity invalidation, and preservation of
  valid prior artifacts.
- Replay: zero simulated/provider calls and successful terminal state.
- Safety: zero network, remote-provider, subprocess, creator/game, and runtime-tracing executions;
  raw debug retention false; private paths absent; isolated working project removed.
- Storage remained approximately linear; serialized M13 state was 18,635,071 bytes.

## Final-head browser evidence

- Chrome passed at 1440x900/100% and effective 720x450/200%.
- Coverage was 27/27 scenes at both zooms, with route-aware plot/citations, deterministic-title
  restoration, zero errors, zero remote requests, and no horizontal overflow.
- Exact simulator cache replay made zero calls. Source, M10/M11/M12 authority, and packaged static
  assets were unchanged.

## Live preview and failure

The exact preview selected 27 synthetic scenes, fact-only mode, M12 included, 87 logical jobs,
63 estimated calls, 324,994 input tokens, and 81,600 output tokens. Limits were 80 calls, 400,000
input, 150,000 output, 550,000 total tokens, 1,800 seconds, and concurrency one. Cost was
unavailable and no monetary limit was represented as known. Provider settings were `{}`; provider
High reasoning and fast-mode state were not encoded or verifiable.

The live run persisted a terminal failed run with 74 failed jobs, 222 `transient_failure` attempts,
24 provider calls, zero input/output tokens, zero artifacts, and no replay. The prepared preview
named consent manifest `m13_consent_3bb95e7426f079172fb8e99e25485a2820a41d05f717a16dc103e037bac67cf3`,
but granted provider requests persisted `m13_consent_d2b91df4b7e1ec713725e17b4f6cd29d632723ea71171578320e720523089cb8`.
The ID changes because `consent_granted` participates in the manifest hash. This violates the
contract's exact preview-bound consent expectation and is a blocking P1 alongside the failed live
acceptance. Per the one-cycle limit, neither was corrected or retried.

## Remaining blockers and limitations

- Public-synthetic canary: the one approved call failed because the provider response did not
  report its resolved model identity; provider usage and token counts were unavailable, and no
  retry was attempted.
- Criterion 15: previewed and transmitted consent-manifest identities are not stable.
- Criterion 20: the one live run failed and zero-call replay did not execute.
- Criterion 22: the independently configured rereview returned FAIL at `9889035`; the single
  corrective cycle passes local gates at `e0fd3bf`, but no final-head independent PASS exists.
- The root task API did not expose a fast-mode selector. The canary manifest/adapter bound
  `fast_mode=false`; this does not claim that the task API independently verified that setting.
- No pull request was created.
