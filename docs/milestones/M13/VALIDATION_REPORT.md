# M13 validation report

Status: Verification blocked by one additional-rereview P1; PR #23 is not currently ready

Baseline: `f67df8a7cb805bf4adf8590585bae700d2f3117f`

Runtime freeze: `3533d49a61e77c76794b4ba8338ccf60ee8201ef`

Validation date: 2026-07-17

## Additional recovered-reservation correction evidence (current)

Correction `a7e242b4534f7217d469308392d932795201cb57` added a reopen regression for the exact prior P1.
At the test-only state, `py -3.12 -m pytest tests/test_m13_workflow.py -k
unresolved_call_reservation_consumes_attempt_ceiling_after_reopen -q` failed 1 test because the
reserved job was resubmitted under `maximum_attempts_per_job=1`. After the product edit, both
unresolved-reservation tests passed; the complete workflow/scheduler pair passed 54 tests in 20.15
seconds. Targeted Ruff, strict mypy, and `git diff --check` passed.

Independent rereviewer `/root/m13_reservation_rereview` returned `FAIL` at exact clean head
`a7e242b`: one P1, no P0/new P2. A provider-free probe showed that two compatible unresolved
reservations for the same historically reused logical attempt collapse to one recovered history
slot, so `maximum_attempts_per_job=2` still admitted a third logical submission. The reviewer also
passed 54 workflow/scheduler tests, a 23-test interaction set, Ruff, strict mypy, and diff checks.
The Release gate started provider-free but was terminated after this blocking verdict rather than
spending further validation time on a head that cannot be PR-ready. Browser, private-scale,
GitHub, push, PR mutation, provider/live, merge, and M14 actions were not run.

## Historical final bounded correction evidence

The exact local lifecycle head is `532eefc933460ed1876a715df1b12a921e24b3c0`; integrated
runtime changes end at `9ab1dbd873420ad4a7f679b87bd39b1ee9b8582b`. The corrected focused
gate passed 227 tests in 135.61 seconds, Ruff, strict mypy over 92 source files, JavaScript syntax,
and both correction-range diff checks. One earlier focused invocation passed its comma-separated
targets as one filename and failed before collection; the corrected array invocation is the
authoritative result.

Final independent reviewer `/root/m13_final_integrated_review` returned `FAIL` at the exact clean,
detached lifecycle head. One P1 remains: recovered unresolved reservations contribute conservative
usage but not per-job attempt history, so reopen can bypass `maximum_attempts_per_job` and reuse the
reserved logical attempt number. The provider-free CPython 3.12 probe seeded logical attempt 1
under a ceiling of 1 and observed cumulative calls increase from 1 to 5. P0: none. New P2: none.
Findings 1 and 3-8 pass; finding 6 is conclusively a false positive.

The reviewer passed 35 focused tests and 9 scheduler/provider boundary tests, Node syntax, diff,
and exact clean-state checks. No edit, provider/network call, private access, push, PR mutation,
merge, or M14 action occurred. Because Track A already used its one authorized bounded correction
and rereview, no second correction loop or downstream Release/browser/private/GitHub acceptance was
started. PR #23 remains at remote head `e17ba5e`; the known-defective local head was not pushed.

## Historical prior PR #23 bounded-correction evidence

The sanitized machine-readable index is `docs/milestones/M13/CURRENT_EVIDENCE.json`. The following
local, browser, private-scale, review, live/replay, and GitHub results pass only for their named
historical heads.

| Command / check | Result | Durable disposition |
|---|---|---|
| Worker failing-first corrections | Exact M12: 4 failed first; resume/accounting: 6 failed first; browser settings: 6 failed/6 passed; privacy: missing shared validator failed collection | Exact worker and integration commits in `CURRENT_EVIDENCE.json` |
| `py -3.12 -m pytest tests -k m13 -q` | 291 passed, 1 expected hardware-wrapper skip, 794 deselected in 260.38 seconds | Public command/result in current index |
| Adjacent M12 modules plus `tests/test_m13_persistence.py` | 139 passed, 1 expected browser-wrapper skip in 19.35 seconds | Public command/result in current index; an earlier PYTHONPATH omission was collection-only |
| `powershell -ExecutionPolicy Bypass -File scripts/validate.ps1 -Tier Release` | 1,079 passed, 7 hardware deselected in 355.38 seconds; Ruff, strict mypy over 92 source files, `pip check`, JavaScript, whitespace, isolated build/install/import/assets/notices all passed | Public command/result in current index |
| Real Chrome acceptance | Passed at 100% and 200%; exact M10/M11/M12/M13 Detail/Evidence navigation; zero remote requests and zero provider calls on navigation/replay | Local sanitized report SHA-256 `ce60b2350b558fc1bf07611b00379186a3cf79a6fe4b6263fcac7f67e858f19b` |
| Provider-free private scale | Passed 1,812 scenes, 2,590 jobs, complete fault/recovery hierarchy, 3,634 claims, exact zero-call replay, unchanged authority/source snapshots, and all safety counters zero | Private-hash-only report SHA-256 `17b1bbb19707698f7730e9a07bb20425a074c6c3707165b424981a19ad960092` |
| Independent targeted review | PASS; no P0/P1/new P2 | Exact head `e79384b`; 105 + 32 + 2 focused tests; detached clean zero-edit review; no provider/external action |
| Final-head live evidence | Passed at exact head `677d88152e100afd154bb54da249582ff0a2ffcd` | Approved browser/backend production path; 24 live calls; complete route-aware publication; exact replay made zero submits/calls/tokens; sanitized report SHA-256 `f97bbfec2f6f1859182c9418dfd92807b006217b6e9498fc5365de96fac0313f` |
| Initial remote PR workflow at evidence head `d5fdcaa` | Repository helper ended pytest at its fixed 900.24-second cutoff after 73%, with no failed test reported; all later quality/build/package checks passed | Historical infrastructure cutoff, not a product-test failure |
| Unbounded GitHub Release at branch head `7bf54042639a781313cf6c924e09a0ee023a86f2` | Run `29604661539` passed: 1,081 tests passed, 7 deselected in 790.16 seconds; Ruff, strict mypy over 92 files, dependency, JavaScript, whitespace, isolated build/install/import, browser assets, and notices passed | Release step 806 seconds; complete job 14 minutes 22 seconds; no repository workflow/process cutoff; no local rerun |

## Current approved final-head live execution and replay

The zero-submit preparation first stopped as required. A copied-source confirmation attempt then
failed closed before provider discovery because the absolute source locator is authority-bound;
that attempt made no submit. The user subsequently authorized the fresh exact manifest and gave
continuing consent through goal completion. One production-path browser/backend run executed at
head `677d88152e100afd154bb54da249582ff0a2ffcd`; no hidden retry or second live execution occurred.

| Durable field | Result |
|---|---|
| Exact preparation | `m13_preparation_a7a83c97243684e472cd50ef5cae3672281b488c07a83a13bc513b563366591e` |
| Exact consent | `m13_consent_c6cfaadb6c48c0882a919ec2048b3889fb94381ca67c534814f7ab9c91e70c05` |
| Provider/settings | OpenAI / `codex_cli_structured` adapter v3; requested/resolved `gpt-5.6-sol`; High; `fast_mode=false`; public synthetic; fact only; M12 included; all 27 current scenes |
| Prepared estimate | 87 logical jobs; 72 calls; 3,247,660 input and 81,600 output tokens; batch maximum 16 items/500,000 characters/100,000 tokens |
| Finite limits | 5,000 calls; 50,000,000 input, 20,000,000 output, and 70,000,000 total tokens; 3,600 seconds; concurrency 4; cost unavailable |
| Representative scope | 27 scenes: 7 common-spine, 6 temporary-branch, 10 persistent-route, and 14 ending scenes; 2 temporary containers, 5 occurrences, 3 loop contexts, 1 M12 result, and 4 M12 prerequisite strings |
| Live usage | 24 calls; 1,524,766 input; 93,316 output; 1,618,082 total tokens; 3,479.184 seconds; peak concurrency one; exact usage; cost unavailable |
| Jobs | Terminal `partial` is valid claim salvage: 90 jobs, 88 succeeded, 2 partial, 0 failed/refused/cancelled/hard-limit, and no unresolved codes |
| Complete hierarchy | 27 scene, 30 segment, 23 chapter, common-story, 2 route, 6 ending, and whole-plot artifacts; zero character artifacts are expected for the narrator-only fixture |
| Claim audit | 1,035 published claims: 946 factual and 89 interpretive; 1,485 resolved citations; 0 suggestions, unknown/out-of-scope references, or DAG cycles; route-aware plot present |
| Exact replay | Fail-closed sentinel observed 0 submit attempts, calls, input/output/total tokens; 90 jobs replayed; artifact payload hashes exact; deterministic rendering SHA-256 `af50407c592537938dcec83c7532ca13ebeac81560c9da0801508410c07aef5b` |
| Safety | Source/archive and M10/M11/M12 authority unchanged; 2,219 durable records inspected; raw debug false; 0 raw prompt or provider-response records; browser remote requests 0 |
| Evidence | Artifact set SHA-256 `2e795955fca24e58f9ee82bcf07d48b50e2953fc563f5c0f7003bbc1057079dc`; sanitized report SHA-256 `f97bbfec2f6f1859182c9418dfd92807b006217b6e9498fc5365de96fac0313f`; preflight SHA-256 `5f26b20f18de7b7c3cf7e6a35c5c6f52d1951d7bb036424d35d8af67b571bc6a`; screenshot SHA-256 `aca50179df28d5a64e6f42e1004ee7e6eb353825d15de50f8d8a655ad0782ebe` |

## Historical exact approved live execution and replay at `740e321`

The sections below preserve prior-head evidence and failures as history. They are not current-head
proof for the reopened correction areas.

The user exactly approved preparation
`m13_preparation_564d42c66a9068ffe4878f1c3d9db59749627220213eca3c17a6d97808342ad4`
and consent
`m13_consent_1de082368bb65c9a835c65364abeb3a78ff6e29316d4509419a6110d015c06de`.
One initial launcher invocation stopped before consent grant or provider submit because its freshly
read preview bytes did not match the approved preview. Rechecking with the installed CPython 3.12
runtime reproduced the exact approved IDs; the exact live execution then ran once. There was no
hidden retry or second provider execution.

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path
& 'C:\Users\prave\AppData\Local\Programs\Python\Python312\python.exe' `
  scripts\m13_live_acceptance.py `
  --output-dir 'tmp\m13-live-preview-740e321\20260717T042635828Z' `
  --model gpt-5.6-sol `
  --reasoning-effort high `
  --confirm-preparation-id 'm13_preparation_564d42c66a9068ffe4878f1c3d9db59749627220213eca3c17a6d97808342ad4'
```

| Durable field | Result |
|---|---|
| Provider identity | OpenAI / `codex_cli_structured` adapter v3; requested/resolved `gpt-5.6-sol`; High; `fast_mode=false` |
| Usage | 13 calls; 616,819 input; 42,505 output; 659,324 total tokens; 837.951 seconds; peak concurrency one; cost unavailable |
| Jobs | 83 pipeline jobs: 81 succeeded, 2 partial, 0 failed/refused/cancelled; no unresolved code |
| Scene salvage | 27 scenes: 25 complete; Foyer retained 4 valid claims and omitted 2 invalid; Courtyard retained 6 valid and omitted 2 invalid |
| Complete hierarchy | 23 segments, 23 chapters, common story, 2 persistent routes, 6 endings, and one route-aware plot; all non-scene hierarchy artifacts complete with full child coverage |
| Character eligibility | Zero character artifacts are expected: the public-synthetic fixture is narrator-only and has no non-empty M11 speaker, so no character group is eligible |
| Claim audit | 222 published claims: 216 factual and 6 interpretive; 758 resolved citations; 0 cycles, unknown, or out-of-scope references |
| Exact replay | Sentinel provider `submit()` would hard-fail; observed 0 submit attempts, calls, input, and output tokens; all 83 jobs were exact cache replays; artifact hashes exact; deterministic rendering SHA-256 `e12a21728a7ef6f4390f83c5e27aa59609c057555b1b66fbc051a9d21b4b8790` |
| Safety | Synthetic source and M10/M11/M12 authority fingerprints remained byte-identical; 798 durable records inspected; raw debug retention false |
| Evidence | `tmp/m13-live-preview-740e321/20260717T042635828Z/live-execution-and-replay.json`; SHA-256 `93a22d669d625b8366f47792d13a7dac98db1c8bab1f7f85bd0a77b46d81a621` |

Aggregate `partial` is the contract-required result of safe claim-level salvage, not an incomplete
hierarchy. The preview's 87 jobs are a conservative upper bound; 83 pipeline jobs were eligible.
The 84th persisted job is a separate authority-fact record, and the narrator-only fixture made
character jobs ineligible. Independent read-only audit `/root/partial_live_audit` returned PASS
for criterion 20 with no remaining P0/P1 after the harness correction.

The original harness expected only aggregate `succeeded`, so it stopped before its built-in replay
even though criteria 5 and 20 permit partial claim salvage. Commit `0aa0415` accepts only
`succeeded` or `partial` terminal publications while continuing to reject failed, refused,
cancelled, and hard-limit states. Its offline regression injects two partial scenes, completes the
hierarchy, and proves zero-call cache replay.

| Post-correction check | Result | Notes |
|---|---|---|
| `powershell -ExecutionPolicy Bypass -File .\scripts\validate.ps1 -Tier Release` at `0aa0415` | Passed | 1,016 passed, 7 deselected in 201.80 seconds; Ruff, strict mypy over 91 files, `pip check`, four JavaScript syntax checks, whitespace, isolated sdist/wheel build/install/import, browser assets, and notices all passed |
| Focused harness correction | Passed | 5 focused tests plus targeted Ruff/strict mypy and diff check; no provider/network call |

## Complete-budget correction at `740e321`

| Command / check | Result | Artifact or notes |
|---|---|---|
| Focused sizing/consent/workflow/scheduler/pipeline/live matrix | 61 passed | Old 400,000-input budget is rejected before consent; callable finite limits bind the complete estimate and rehash consent |
| Targeted Ruff, strict mypy, `git diff --check` | Passed | Seven runtime/test files; no provider call |
| `powershell -ExecutionPolicy Bypass -File .\scripts\validate.ps1 -Tier Release` | Passed | 1,015 passed, 7 deselected in 190.96 seconds; every Ruff, strict mypy, dependency, JavaScript, whitespace, isolated build/install/import/assets/notices gate passed |
| Independent read-only final-budget review | PASS; no P0/P1 | `/root/final_budget_rereview`; 126 review tests plus 14 changed-module tests; no tracked edits or provider calls |
| Corrected provider-free private acceptance | Passed in about 16m35s | 1,812 scenes; complete hierarchy/fault/recovery; exact zero-call replay; all inputs unchanged; zero network/provider/game execution; `tmp/m13-provider-free-private-740e321/acceptance.json`, SHA-256 `13226a0d25cff4a63d33f8bdd9d8e1a13f19d2f36a51c0c9e1003cd6a832b0dc` |
| Stable zero-submit live preview | Passed twice; zero submits | `tmp/m13-live-preview-740e321/20260717T042635828Z/consent-preview.json`; SHA-256 `a2fbe4acae8be57e11ef9560a72dc9aa3431df5d95a177f319ecd1ad9063e996` |

The fresh manifest binds preparation
`m13_preparation_564d42c66a9068ffe4878f1c3d9db59749627220213eca3c17a6d97808342ad4`
and consent `m13_consent_1de082368bb65c9a835c65364abeb3a78ff6e29316d4509419a6110d015c06de`.
It estimates 87 jobs, 65 calls, 2,463,527 input tokens, and 81,600 output tokens. Finite limits
are 130 calls, 4,927,054 input, 163,200 output, 5,090,254 total tokens, 7,200 seconds, and
concurrency one. Cost is explicitly unavailable. The live policy permits one attempt per job, so
transient, malformed, split, and repair retries cannot consume hidden calls. The 25,000-token
per-call runtime allowance is calibrated from the failed run and is not claimed as a provider-
guaranteed upper bound. The preview itself made no call; the exact execution authorized later is
recorded above.

The corrected private complete-run estimate is 2,590 logical jobs, 892 calls, 31,703,062 input
tokens, and 2,227,600 output tokens. The simulator used 171 initial and 6 recovery calls and zero
replay calls. Peak working set was approximately 6.2 GB; this is a harness performance limitation,
not an acceptance failure.

## Final-head model-identity correction at `5be797c`

| Command / check | Result | Artifact or notes |
|---|---|---|
| Focused provider/canary/consent/cache/scheduler matrix | 59 passed in 3.13 seconds | Adapter v3 accepts omitted redundant metadata only by retaining exact locked `--model`; malformed, conflicting, or different metadata still fails closed |
| Targeted Ruff, strict mypy, `git diff --check` | Passed | Three runtime/test files changed; adapter v2 and v3 cache identities differ |
| Independent read-only correction audits | PASS; no P0/P1 | `/root/model_identity_audit`, `/root/identity_test_audit`, and post-commit `/root/final_fix_rereview`; no provider calls or edits |
| Fresh public-synthetic schema-canary preview | Passed locally; zero calls | `tmp/m13-schema-canary-preview-5be797c.json`; SHA-256 `732760505cde292f24b7d8c3a175ffb89277a0bd8973aa151d7554d7e7408520` |
| Exactly one fresh public-synthetic schema canary | Passed in 6.256 seconds; exit 0; no retry | Adapter/schema v3, `gpt-5.6-sol`, High, `fast_mode=false`, one call, public fact only; `tmp/m13-schema-canary-execution-5be797c/result.json`; SHA-256 `bd044b43a45a019d7a17b3a6a38e45c656da14bd5d5021cefeb5df0f58c589af` |
| `powershell -ExecutionPolicy Bypass -File .\scripts\validate.ps1 -Tier Release` | Passed once in 210.82 seconds | 1,012 passed, 7 deselected in 194.59 seconds; Ruff, strict mypy over 91 files, `pip check`, four JavaScript checks, whitespace, isolated sdist/wheel build/install/import/assets/notices all passed |
| Fresh adapter-v3 zero-submit live preview | Passed in 2.017 seconds; provider submits zero | `tmp/m13-live-preview-5be797c/20260717T030102350Z/consent-preview.json`; SHA-256 `5cd30c993612c0c4a99e661aaa2f505c4d8a71f0588028686cd7910cc6b34a76`; preparation `m13_preparation_f22f1d...`; consent `m13_consent_9e3a246...` |

The fresh exact live manifest binds adapter/schema v3, prompt v4, `gpt-5.6-sol`, High reasoning,
`fast_mode=false`, fact-only mode, M12 inclusion, 87 logical jobs, 63 estimated calls, 324,994
estimated input tokens, 81,600 estimated output tokens, an 80-call limit, 1,800-second timeout,
and concurrency one. Cost remains unavailable. No live story content was transmitted by preparing
or verifying this manifest.

## Exact adapter-v3 live execution at `5be797c`

The user exactly confirmed preparation
`m13_preparation_f22f1d9b7d1110dec242d7b56928c4f0c02dc168697ed986915aa5030d80f6eb`
and consent
`m13_consent_9e3a24626be81561498eddcec29afa66e9793ef6c879d5425889276a6cc750aa`.
The harness ran once, made no retry, and stopped before replay with terminal state `hard_limit`.
The granted and transmitted consent ID remained exactly equal to the previewed ID.

| Durable field | Result |
|---|---|
| Provider identity | OpenAI / `codex_cli_structured` adapter v3; requested/resolved `gpt-5.6-sol`; High; `fast_mode=false` |
| Usage | 3 provider calls; 395,221 input; 11,142 output; 406,363 total tokens; 218.358 seconds; concurrency one; cost unavailable |
| Jobs | 27 succeeded scene jobs; 23 summary-segment jobs stopped at `hard_limit` before an attempt |
| Durable output | 27 scene artifacts, 27 cache entries, 82 claims; no segment/chapter/route/ending/character/plot artifact |
| Replay | Not reached because the first run was not fully successful |
| Safety | Synthetic source SHA-256 remained `0b83ffd3...14d`; all persisted M13 records retained consistent authority bindings; no raw debug retention |
| Evidence | `tmp/m13-live-preview-5be797c/20260717T030102350Z/failure-result.json`, SHA-256 `cb9c9e22ea5cc0034fa5261eee442a59f2cab0b18d0de3a5fef70b31ba0b00fd`, and `live-failure.txt` |

Persistence records only generic `hard_limit`. Scheduler preflight rules and exact usage support
`input_token_limit` as an inference: 4,779 of 400,000 input tokens remained before the next
hierarchy batch, while call (3/80), output-token (11,142/150,000), total-token
(406,363/550,000), and elapsed-time (218.358/1,800 seconds) limits were not exhausted. No fourth
provider call occurred.

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

## Remaining limitations

- The historical adapter-v2 public canary failure remains preserved above; adapter-v3 correction
  `5be797c` and its one fresh public canary now pass without weakening conflicting-model checks.
- Criterion 15: adapter-v3 live consent identity is now proven stable across preview, grant, and
  provider requests.
- Historical live failures remain preserved above. The final exact `740e321` live execution and
  fail-closed replay satisfy criterion 20; the two partial scenes are valid claim-level salvage.
- Final-head independent budget review and post-live evidence audit both pass with no unresolved
  P0/P1. Post-correction focused and Release results are recorded in this report.
- The root task API did not expose a fast-mode selector. The canary manifest/adapter bound
  `fast_mode=false`; this does not claim that the task API independently verified that setting.
- Explicitly approved draft [PR #23](https://github.com/nmpraveen/renpy-story-mapper/pull/23) is
  open and mergeable. It remains unmerged and requires separate approval before merge.
