# M13 live-provider acceptance failure

Status: Failed; no retry authorized or attempted

Runtime freeze: `e0fd3bf3dba34a2d936028f3df8773e69d9fc1c8`

Date: 2026-07-16

## Exact approved preview

- Provider/adapter: OpenAI / `codex_cli_structured` v1; CLI 0.144.0
- Requested/resolved model in preview: `gpt-5.6-sol`
- Provider settings: `{}`; High reasoning and fast-mode state were not encoded or verified
- Privacy: fact-only; M12 included; raw debug retention off
- Scope: 27 synthetic scenes, 87 logical jobs, 63 estimated provider calls
- Estimate: 324,994 input and 81,600 output tokens
- Limits: 80 calls; 400,000 input; 150,000 output; 550,000 total; 1,800 seconds;
  concurrency one; cost unavailable
- Preparation: `m13_preparation_f331d17b9e6bc8f3a476a2166c74a4fd8092d9b2fecc20f920fd5858080c4dc6`
- Previewed manifest: `m13_consent_3bb95e7426f079172fb8e99e25485a2820a41d05f717a16dc103e037bac67cf3`
- Preview SHA-256: `406ee106aa7f1bc68001d49c928856963ff67e3cdd6916270d19283285f38fb6`

The user approved the exact manifest, then separately approved external transmission after the
approval reviewer classified the synthetic repository-derived facts as private content. The first
command request was rejected before process launch and made zero provider calls. The unchanged
command was then permitted and launched once.

## Command

```powershell
$env:PYTHONPATH=(Join-Path $pwd 'src')
& 'C:\Users\prave\AppData\Local\Programs\Python\Python312\python.exe' `
  scripts\m13_live_acceptance.py `
  --output-dir 'tmp\m13-parallel-live-preview-e0fd3bf\worker-019f6d0f-b146-7f12-9294-3af8f7bc0bc7' `
  --model gpt-5.6-sol `
  --confirm-preparation-id 'm13_preparation_f331d17b9e6bc8f3a476a2166c74a4fd8092d9b2fecc20f920fd5858080c4dc6'
```

Exit code: 1 after approximately 37 seconds.

Harness error: `AssertionError: live hierarchy did not fully succeed: failed`.

## Preserved sanitized result

The pending synthetic project remains in the output directory. SHA-256 after failure:
`b9fa08df7431bd9fac15ef9bc8830456ff173a627f0c228b45fe4616586756cf`.
The synthetic source remained SHA-256
`0b83ffd34e91ff6867b6dd2ef266c3eca3bb930292e8fa30cc756dc218fbc14d`.
No `acceptance.json` was created.

Read-only persistence inspection found:

- run state: failed;
- jobs: 74 failed, 0 succeeded, 0 partial, 0 cancelled;
- attempts: 222, all sanitized `transient_failure` (three attempts per job);
- provider calls: 24;
- recorded input/output tokens: 0/0;
- artifacts: none;
- unresolved code: `common_story_unavailable`;
- zero-call replay: not reached.

No raw prompt or provider response was inspected or added to this report.

## Blocking consent finding

The persisted run/provider requests used consent ID
`m13_consent_d2b91df4b7e1ec713725e17b4f6cd29d632723ea71171578320e720523089cb8`,
not the previewed/approved ID `m13_consent_3bb95e...`. `ConsentManifest.manifest_id` hashes the
serialized `consent_granted` field, so changing it from false to true changes the ID after preview.
The preparation comparison still succeeds by toggling the flag back, but the provider request is
not bound to the identifier shown to the user. This is a P1 exact-consent defect under criterion 15.

Per the user's one-correction-cycle rule, runtime code was not changed and the live run was not
retried. A future attempt requires a separately approved correction, final-head independent review,
fresh preview, and new exact consent.
