# M05 Independent Adversarial Review

- Task ID: `019f540f-eb55-7bd3-8293-02ac26f5f880`
- Review base: `9059acdb24aa17fd3259c2632f89e718a8186daf`
- Branch: `codex/m05-independent-review`
- Worktree: `C:\Users\prave\.codex\worktrees\bda7\Renpy`
- Runtime: Windows CPython 3.12.10
- Status: **Return**

## Findings

### P2 - The cloud provider boundary does not enforce the locked Luna model

`CodexCliProvider.command()` adds `--model` only when its caller supplies a model
(`provider.py:505-533`). A consented direct ChatGPT request with the default `None` model therefore
runs with High reasoning and disabled fast mode but without the required `--model gpt-5.6-luna`.
`OrganizationOptions` also accepts `model=None` and arbitrary nonempty `model_profile` values
(`organization_workflow.py:79-85,143-170`), even though the provider command always selects High for
ChatGPT. That permits persisted/cache profile metadata such as `balanced` to disagree with the
actual command.

Minimal reproduction: `test_reproduction_cloud_provider_command_is_not_intrinsically_luna_locked`
and `test_reproduction_workflow_options_accept_mislabeled_execution_profile` in
`tests/test_m05_independent_review.py`.

Responsible subsystem: organization provider and UI organization workflow option validation.

### P2 - Integrated workflow cache identity omits prompt constraints

The workflow hashes only `request.payload` (`organization_workflow.py:234-252`) before querying the
persistent cache. The exact provider prompt also contains stage, scope, required/context IDs, fact
IDs, evidence IDs, and allowed characters (`contracts.py:168-252`). The repository's dedicated
`build_cache_key()` includes several of those omitted fields (`cache.py:35-68`), but the integrated
workflow does not call it. Two different provider prompts can consequently share the same
persistent workflow cache identity and skip a required model call.

Minimal reproduction: `test_reproduction_workflow_cache_hash_omits_prompt_constraints`.

Responsible subsystem: UI organization workflow/cache integration.

### P2 - Claim evidence is checked project-wide, not against its target event or arc

Stage-1 events retain request-wide allowed evidence (`organization_workflow.py:983-996`), and final
draft validation checks only that each claim evidence ID exists anywhere in
`presentation_evidence` (`story_organization.py:1600-1626`). A claim attached to the first event is
accepted when its sole evidence belongs exclusively to a different event. This defeats exact
claim-to-evidence traceability while retaining syntactically valid IDs.

Minimal reproduction: `test_reproduction_claim_can_cite_evidence_outside_its_target_event`.

Responsible subsystem: organization workflow reconciliation and story-organization draft
validation.

### P2 - Live acceptance evidence is incomplete and not independently reproducible

`TASKS.md:102-113` records aggregate prose for the synthetic Luna run, cached retry, apply, reopen,
and UI harness. It does not record the exact commands, project/output locations, result JSON,
screenshot paths/hashes, before/after deterministic hashes, or database-growth measurements. It
also contains no completed separately consented `script small new.rpy` smoke run, which remains a
required acceptance source in `GOAL.md:29-31,59-64` and `MASTER_PLAN.md:686-715`. At review base,
`docs/milestones/M05/` contains only `GOAL.md` and `TASKS.md`; the required completion report,
screenshots, and infographic are not present. The repository therefore cannot substantiate or
independently rerun the claimed live acceptance without external state that was not delegated.

Responsible subsystem: milestone orchestration and acceptance evidence.

No P0, P1, or P3 correctness/security findings were identified. The unresolved P2 findings block
M05 acceptance under `GOAL.md:65-68`.

## Verification

- `python.exe --version`: Python 3.12.10.
- Focused M05/domain suite: 209 passed in 10.32 seconds.
- Review reproductions: 4 passed in 0.18 seconds.
- Full `python.exe -m pytest`: 347 passed in 15.23 seconds.
- `python.exe -m ruff check src tests scripts`: passed.
- `python.exe -m mypy src\renpy_story_mapper`: passed; 34 source files.
- `python.exe -m pip check`: passed; no broken requirements.
- `git diff --check`: passed.
- `git diff --check main..9059acd`: passed.

The existing focused/full suites passing does not invalidate the reproductions: the added review
tests intentionally assert the currently unsafe accepted behavior so the defects remain executable
without modifying production code.

## Performance and security assessment

- The representative layout and scale tests pass, and the focused M05 suite completed quickly.
  The supplied live UI harness could not be rerun because its required accepted-plus-pending
  `.rsmproj` input and output evidence were not stored or identified in the repository.
- Consent is checked before provider process creation; execution is ephemeral/read-only and disables
  web, shell, plugins, apps, hooks, browser/computer use, MCP elicitation, multi-agent, and fast mode.
  Error messages are sanitized and cancellation uses bounded terminate/kill waits.
- The remaining security/configuration risk is fail-open model selection at the provider/workflow
  boundary. The remaining correctness risks are stale semantic cache hits and cross-target claim
  evidence.

## Recommendation

Return M05 to the responsible provider/workflow, cache integration, story-organization validation,
and orchestration owners. Re-review after the three production defects are fixed and focused
regressions prove fail-closed behavior, and after repository-backed evidence records the secondary
real-script smoke run and the exact live/UI/hash/growth acceptance results.
