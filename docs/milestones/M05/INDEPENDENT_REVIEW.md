# M05 Independent Adversarial Review

- Task ID: `019f540f-eb55-7bd3-8293-02ac26f5f880`
- Original review base: `9059acdb24aa17fd3259c2632f89e718a8186daf`
- Blocker-fix re-review base: `fc239ce1df6216c20daf347f635e01926f1c3a59`
- Branch: `codex/m05-independent-review`
- Worktree: `C:\Users\prave\.codex\worktrees\bda7\Renpy`
- Runtime: Windows CPython 3.12.10
- Code-fix status: **Accepted**
- Milestone acceptance status: **Return for acceptance evidence only**

## Closed code findings

### Closed P2 - Luna, High reasoning, and disabled fast mode are intrinsic

Closed at `fc239ce`. The ChatGPT provider constructor, model setter, and command builder normalize a
missing model to `gpt-5.6-luna` and reject every conflicting model
(`provider.py:285-309,363-373,515-548`). The command always includes High reasoning and disables
`fast_mode`. The workflow independently rejects any ChatGPT options that are not Luna plus the High
profile before provider construction or consent (`organization_workflow.py:137-155`).

The strengthened adversarial test verifies the default command and conflicting constructor,
setter, command, and workflow inputs:
`test_cloud_provider_command_is_intrinsically_luna_locked` and
`test_workflow_rejects_mislabeled_execution_profile`.

### Closed P2 - Cache identity includes every prompt-affecting request field

Closed at `fc239ce`. `build_cache_key()` hashes stage, scope, payload, ordered IDs, required IDs,
context-only IDs, fact IDs, evidence IDs, and character names (`cache.py:35-71`). The integrated
workflow now uses that exact input hash before every persistent cache lookup
(`organization_workflow.py:229-265`). Provider mode, model profile/fingerprint, prompt version, and
schema version remain part of the outer cache identity.

`test_cache_hash_includes_prompt_constraints` now changes each material field independently and
proves that every resulting input hash differs.

### Closed P2 - Claim evidence is bound to its target event or arc

Closed at `fc239ce`. Stage-1 reconciliation retains only evidence and fact permissions attached to
the exact grouped beats (`organization_workflow.py:959-1028`). Candidate construction drops event
or arc claims outside the target membership (`organization_workflow.py:1618-1656`). The domain
validator independently derives evidence sets from each event's beats and each arc's member events,
then rejects cross-target evidence (`story_organization.py:1604-1660`).

`test_claim_cannot_cite_evidence_outside_its_target_event_or_arc` proves rejection for both an event
target and an arc target.

No unresolved P0-P3 production correctness or security finding remains from this bounded re-review.

## Remaining acceptance/documentation blocker

### Open P2 - Live acceptance evidence is incomplete and not independently reproducible

This is not a production-code defect and was not changed by `fc239ce`. `TASKS.md:102-116` records
aggregate prose for the synthetic Luna run, cached retry, apply/reopen behavior, and UI harness, but
does not identify exact commands, retained result JSON, project/output locations, screenshot paths
and hashes, deterministic before/after hashes, or database-growth measurements. No completed,
separately consented `script small new.rpy` smoke run is recorded, although it remains required by
`GOAL.md:29-31,59-64` and `MASTER_PLAN.md:686-715`.

At `fc239ce`, `docs/milestones/M05/` contains `GOAL.md`, `TASKS.md`, and this review only. The
required `COMPLETION_REPORT.md`, screenshots, and native `INFOGRAPHIC.png` are absent. The supplied
native UI harness still cannot be independently rerun because its accepted-plus-pending
`.rsmproj` input and prior output evidence are not stored or identified in the repository.

Responsible subsystem: milestone orchestration and acceptance evidence.

## Re-review verification

- `python.exe -m pytest tests\test_m05_independent_review.py -q`: 4 passed in 0.18 seconds.
- `python.exe -m pytest tests\test_m05_independent_review.py tests\test_m05_organizer.py
  tests\test_m05_story_explorer.py tests\test_story_organization.py -q`: 172 passed in 9.57
  seconds.
- `python.exe -m ruff check` on the four changed production modules and four relevant test files:
  passed.
- `python.exe -m mypy` on `provider.py`, `cache.py`, `organization_workflow.py`, and
  `story_organization.py`: passed; no issues in 4 source files.
- `git diff --check`: passed after the review update.

Original review verification at `9059acd` remains recorded in Git history: 209 focused tests and
347 full tests passed, together with repository-wide Ruff, strict mypy, `pip check`, and whitespace
checks.

## Risks and recommendation

- The three code fixes are defense-in-depth: both provider and workflow enforce the command lock;
  both workflow filtering and domain validation enforce claim evidence locality; cache material is
  tested field by field.
- The re-review did not rerun live cloud organization, access canonical data, or rerun the native UI
  harness because those actions and inputs remain outside the delegated scope.
- Remaining risk is evidentiary rather than an identified code defect: the milestone cannot prove
  the required secondary smoke run, immutable deterministic hashes, UI captures, or storage-growth
  result from repository contents.

Accept the `fc239ce` production blocker fixes. Keep M05 milestone acceptance open and return only to
the orchestration/documentation owner until the missing repository-backed acceptance evidence and
completion artifacts are supplied.
