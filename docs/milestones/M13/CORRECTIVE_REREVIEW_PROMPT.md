# M13 corrective independent rereview prompt

Invocation settings:

- Model: `gpt-5.6-sol`
- Reasoning effort: `high`
- Fast mode: disabled with `--disable fast_mode`
- Sandbox: `read-only`
- User configuration: ignored
- Session persistence: ephemeral
- Reviewed range: `04082c011baa68eebe840c8961ba8662daf2f900..988903529d08cd5890c116b6c1adfe070b76ab57`

Exact reviewer prompt:

> Perform one independent, read-only corrective code rereview of commit range
> `04082c011baa68eebe840c8961ba8662daf2f900..988903529d08cd5890c116b6c1adfe070b76ab57`
> in the current repository. Do not edit or create files, do not run the full test suite, do not
> use web or external tools, and do not review unrelated M13 implementation. Read the approved M13
> contract and only the files/tests needed to assess closure of these three prior P1 findings:
> (1) exact route-specific M12 authority lost through the claim propagation cap; (2) a validated
> artifact exceeding the browser's 256-claim contract after mandatory M12 insertion; and (3) a
> factual claim merging incompatible routes or temporal contexts. Also identify any newly
> introduced P0/P1 correctness, security, privacy, authority, or acceptance regression in this
> cumulative correction. In particular, verify that comparison/ordered-summary scope cannot be
> re-atomized at a later DAG level, mandatory M12 claims remain bounded without the former 32-claim
> abort, and the committed browser asset manifest matches changed assets. You may run only narrow
> focused tests directly relevant to a suspected finding. Return a concise Markdown report listing
> each finding as `P0`, `P1`, `P2`, or `P3` with exact file/line evidence and a final verdict of
> `PASS` or `FAIL`. P0/P1 blocks; P2/P3 may be documented. If there are no findings, say so
> explicitly. Do not claim the Release suite or live-provider acceptance passed.

## Attempts and completed result

The configured invocation was attempted after the runtime code freeze while Release validation ran:

```powershell
Get-Content -Raw docs\milestones\M13\CORRECTIVE_REREVIEW_PROMPT.md | codex exec --ephemeral --ignore-user-config --ignore-rules --strict-config --disable fast_mode -c 'model_reasoning_effort="high"' --model gpt-5.6-sol --sandbox read-only --output-last-message tmp\m13-corrective-rereview-9889035.md -
```

That first action was rejected before transmission because it would disclose private repository
code to an external model service. No review content left the machine in that attempt. The user
then explicitly approved that external review disclosure, and the same exact invocation completed.

Completed reviewer session: `019f6d01-2c81-71c0-b459-d2a99ccc5be7`.

The CLI reported model `gpt-5.6-sol`, provider `openai`, reasoning `high`, read-only sandbox,
ephemeral persistence, and fast mode disabled by the explicit invocation flag. It edited no files
and did not run the full suite. The exact report is preserved in
`tmp/m13-corrective-rereview-9889035.md` with SHA-256
`be23d6fd6cf85f9e3f8c1ef746839fef993ac1ab40f46d45fd3a4650b0120a23`, and durably copied with
post-review disposition in `CORRECTIVE_REREVIEW_REPORT.md`. Verdict: `FAIL`, two P1 findings.
