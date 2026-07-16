# M12 completion report

Status: PR ready

Validated product commit: `40c10fd9bb31e9303efeb302dacd081e1007911c`

Pull request: [PR #22](https://github.com/nmpraveen/renpy-story-mapper/pull/22), open and unmerged

Changes-requested base: `a02151ebc45d2d05efc6d582a8757fbca87aa6d5`

## Outcome

M12 provides an on-demand, deterministic, bounded, cacheable static answer to “How do I reach this
scene or outcome?” From M10-authoritative state and M11/M10 destinations, it returns ordered human
scenes, visible choices, deterministic instructions, requirements and earlier satisfying effects,
persistent commitments, conservative uncertainty, exact provenance, alternatives, evidence,
cancellation, cache replay, and JSON export without executing Ren'Py, the game, creator code, a
provider, or a remote request.

All four changes requested on PR #22 are resolved without redesigning M12 or changing M10/M11
authority, persistence, cancellation, cache, UI, evidence, or export:

1. Supported requirements now intersect chronologically and contradictory states are pruned.
2. Completed generic call frames are popped, including correct nested return behavior.
3. Search paths use parent-linked bounded prefixes and scale approximately linearly.
4. Exact M10-authorized loops accelerate conservatively, including exact intermediate-node exits.

## Final acceptance

| Check | Result |
|---|---|
| Direct solver and scale corrections | 64 passed |
| Fast | 39 passed |
| Focused M12 | 123 passed, 1 opt-in browser wrapper skipped and run separately |
| Release | 788 passed, 6 hardware-sensitive deselected; Ruff, strict mypy, JavaScript, dependency, package, isolated install/import, assets, and notices passed |
| Persistence/fault/private harness | 32 passed; emergency abort replay 10/10 |
| 500/1,000/2,000 linear routes | Passed under normal v1 budgets with approximately 2x accounting/prefix growth |
| Exact grind over 16 repetitions | Passed at exact repeat count 25 |
| Real Chrome | Passed at 100% and 200%, including cache, cancellation, evidence, layout, and export |
| Real private acceptance | Passed for five selected targets with unchanged inputs and zero execution/remote counters |
| Final independent review | `PASS` on literal diff `a02151e..40c10fd`; no blocking finding |

Exact commands, counts, hashes, artifacts, limitations, and the before/after review record are in
[`VALIDATION_REPORT.md`](VALIDATION_REPORT.md).

## Review resolution

The final reviewer identified an intermediate-loop exit that needed a partial-cycle phase. Before
the fix, the solver could overshoot trust 25 or incorrectly call the route state-infeasible. Commit
`40c10fd` tracks the exact phase at each exit. Both `trust >= 25` and
`trust >= 25 and trust < 27` now return the shortest exact route: 13 forward edges, 12 return edges,
and trust 25. The independent re-review returned `PASS`.

## Integration and lifecycle

- Integrated diff reviewed against the amended M12 contract and exclusions: Yes
- Required checks and evidence complete: Yes
- Blocking findings resolved: Yes
- Existing PR #22 updated; no second branch or PR: Yes
- PR merged: No; merge remains approval-gated to the user
- Repository lifecycle: `PR ready`; repository `Complete` remains reserved for post-merge reconciliation

The earlier native goal was completed at the prior genuine PR-ready state. The user explicitly
requested a bounded continuation rather than an M12 restart, so no replacement goal was created.
Task controls still did not expose verifiable model/reasoning/fast-mode selectors; no product logic
was added for that orchestration limitation.
