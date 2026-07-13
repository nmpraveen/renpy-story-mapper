# M08 AI story-understanding evaluation core

## Boundary

`renpy_story_mapper.evaluation` compares a deterministic technical baseline with an already
validated organization artifact. Importing or running it cannot construct an organization
provider. The default command path performs zero provider calls, resolves no external path slots,
and makes no network request.

The checked-in manifest and schema are:

- `tests/fixtures/m08/evaluation-manifest.json`
- `tests/fixtures/m08/evaluation-manifest.schema.json`

They cover the fingerprinted synthetic complex fixture, user-supplied small real `.rpy`,
user-supplied small
recovered `.rpyc`, and four bounded MsDenvers windows. External text, absolute paths, recovered
scripts, archives, and walkthrough text are forbidden. Walkthrough expectations may be used only
after organization as a human/evaluation reference.

## Window contract

A route scope is not an evaluation bound. Every `EvaluationScope.bounds.window` has:

- `window_id`, `parent_scope_id`, and `selection_mode="bounded_window"`;
- the complete ordered `expected_node_ids` and `expected_evidence_ids`;
- exact `boundary_before_node_ids` and `boundary_after_node_ids`;
- `id_set_sha256`, computed over those fields with sorted-key compact UTF-8 JSON;
- hard `max_nodes` and `max_evidence` limits; and
- `require_strict_subset`, which requires both parent counts to exceed the selected counts and at
  least one before/after context node.

Checked-in external scopes hold `id_set_slot` and `id_set_fingerprint_slot` instead of IDs. Such a
scope is intentionally unresolved and always fails the `exact_bounded_window` guardrail. A local
scope builder must replace the slots with complete deterministic IDs, context, and the matching
SHA-256. It must also replace expectation slot tokens with exact IDs. It must never put story text
in the manifest.

The fresh MsDenvers chronological spine is parent scope
`route_scope_13004aa8febf656c5f04` with 13,937 evidence records. The manifest defines four separate
windows—opening, temporary detour, persistent route, and ending—each capped at 24 nodes and 256
evidence records. Selecting the parent scope itself fails the size limit and strict-subscope check.

The follow-on scope-builder/API worker must emit this exact technical baseline shape:

```json
{
  "schema_version": 1,
  "scope_id": "manifest-scope-id",
  "window": {
    "window_id": "manifest-window-id",
    "parent_scope_id": "deterministic-route-scope-id",
    "selection_mode": "bounded_window",
    "node_ids": ["complete ordered deterministic node IDs"],
    "evidence_ids": ["complete ordered deterministic evidence IDs"],
    "boundary_before_node_ids": ["ordered context IDs outside selection"],
    "boundary_after_node_ids": ["ordered context IDs outside selection"],
    "parent_scope_node_count": 1,
    "parent_scope_evidence_count": 1
  },
  "authority": {
    "element_ids": ["exactly window.node_ids"],
    "edges": [{"id": "existing ID", "source_id": "existing ID", "target_id": "existing ID"}],
    "fact_ids": ["existing deterministic fact IDs"],
    "evidence": [{"id": "exactly an ID in window.evidence_ids", "subject_ids": ["existing IDs"]}]
  }
}
```

The worker must preserve deterministic order, include every selected ID once, prove that boundary
context is outside the selection, report full parent counts, and refuse a selected window that
exceeds the manifest cap or equals its strict parent. It must not silently truncate and label the
result complete.

## Candidate and browser contracts

`EvaluationCandidate` schema version 1 contains:

- unchanged `authority` copied from the baseline;
- ordered groups with concise title/summary, existing member IDs, and evidence-backed claims;
- feature annotations for character development, route meaning, temporary detours, persistent
  routes, loops, and endings;
- eligible/AI-covered/technical-fallback IDs;
- calls, tokens, elapsed milliseconds, attempts, cache hits/misses, cancellation/resume counts,
  and replay state;
- provider identity (`gpt-5.6-luna`, `high`, `fast_mode=false`) when invoked; and
- provenance flags proving no walkthrough dependency or embedded external text.

`EvaluationReport.comparison` is the precise browser-worker input. Its stable top-level fields are:

```text
schema_version, scope_id, decision, technical, ai,
criteria, guardrails, coverage, accounting
```

`technical` contains the authority SHA-256, exact window snapshot, and element/edge/fact/evidence
counts. `ai` contains run ID, status, provider profile, ordered groups, and annotations. `criteria`
rows contain `id`, `label`, `weight`, normalized `score`, and `detail`. `guardrails` rows contain
`id`, `passed`, and `detail`. The browser must treat `decision="rejected"` as technical fallback,
must show partial/cancelled coverage honestly, and must never infer acceptance from nominal status.

## Rubric and fail-closed rules

The weighted rubric covers scene boundaries (8), meaningful events (8), concise titles (4),
concise summaries (4), character development (6), route meaning (8), temporary detours (5),
persistent routes (8), loops (6), endings (8), evidence support (10), AI coverage (8), technical
fallback (5), calls/tokens/time (4), cache/replay (4), deterministic authority (10), and walkthrough
independence (4). The normalized pass threshold is 0.85.

Scoring cannot override a failed guardrail. Rejection is mandatory for a scope/window mismatch,
unresolved or expanded window, authority changes, invented IDs/edges/facts, crossing membership,
missing or unrelated evidence, inconsistent coverage, misleading complete status, hard
resource-budget excess, inconsistent attempt/cancellation/replay accounting, wrong live provider
profile, walkthrough dependence, or
embedded external text. Partial and cancelled candidates may produce a comparison payload but are
never accepted.

## Non-live commands (Windows CPython 3.12)

From the repository root:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
py -3.12 -m renpy_story_mapper.evaluation validate-manifest `
  --manifest .\tests\fixtures\m08\evaluation-manifest.json
py -3.12 .\scripts\m08_non_live_acceptance.py `
  --output-dir .\artifacts\m08\non-live
py -3.12 -m renpy_story_mapper.evaluation evaluate `
  --manifest .\tests\fixtures\m08\evaluation-manifest.json `
  --scope complex-fixture `
  --baseline .\tests\fixtures\m08\technical-baseline.json `
  --candidate .\tests\fixtures\m08\validated-ai.json `
  --output .\artifacts\m08\complex-report.json `
  --comparison-output .\artifacts\m08\complex-browser-comparison.json
```

## Later orchestrator-authorized live Luna run

The browser product—not this evaluator—owns exact per-run cloud consent and story transmission.
After a scope-builder/API worker lands, the orchestrator should keep all resolved manifests and
story-bearing run files outside the repository, launch the loopback product, explicitly approve
the displayed bounded window, and export only the technical baseline plus validated organization
contract. The evaluator then runs locally over those exported contracts:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
$LiveRoot = (Resolve-Path $env:M08_LIVE_RUN_ROOT).Path
py -3.12 -m renpy_story_mapper.web.launcher
# In the opened loopback browser: select the resolved window, review its exact counts/hash,
# grant consent for that run only, run Luna organization, validate, and export the two contracts.
py -3.12 -m renpy_story_mapper.evaluation validate-manifest `
  --manifest "$LiveRoot\resolved-manifest.json"
py -3.12 -m renpy_story_mapper.evaluation evaluate `
  --manifest "$LiveRoot\resolved-manifest.json" `
  --scope $env:M08_LIVE_SCOPE_ID `
  --baseline "$LiveRoot\technical-baseline.json" `
  --candidate "$LiveRoot\validated-organization.json" `
  --output "$LiveRoot\evaluation-report.json" `
  --comparison-output "$LiveRoot\browser-comparison.json"
```

Before consent, the browser must display the resolved node/evidence counts, boundaries, hashes,
provider `gpt-5.6-luna`, reasoning `high`, and fast mode disabled. Reopening, comparison, and replay
must use the persisted candidate and make zero calls. No command above reads a path slot or sends
story text; provider transmission remains an explicit later browser action.
