# M13 corrective independent rereview report

Reviewed range: `04082c011baa68eebe840c8961ba8662daf2f900..988903529d08cd5890c116b6c1adfe070b76ab57`

Settings: `gpt-5.6-sol`; reasoning `high`; fast mode disabled; ephemeral; strict config; ignored user
config/rules; read-only sandbox

Reviewer session: `019f6d01-2c81-71c0-b459-d2a99ccc5be7`

Original artifact: `tmp/m13-corrective-rereview-9889035.md`

Original SHA-256: `be23d6fd6cf85f9e3f8c1ef746839fef993ac1ab40f46d45fd3a4650b0120a23`

## Exact reviewer report

### Findings

- **P1 — Exact M12 route context can still be replaced by unrelated child context.** Authority
  claims are added without structural context in `reduction.py:264`, while exactness validation
  permits one M12 handle plus additional non-authority child handles in `validation.py:535`.
  Context resolution then considers only those non-authority children (`validation.py:176`) and
  persists that result instead of the route-bound fallback (`reduction.py:422`). A route-A M12
  fact supported alongside a route-B or common child can therefore acquire that child's context.
  If later omitted, deterministic salvage also recreates it as `atomic` unconditionally
  (`validation.py:418`), bypassing inherited comparison/ordered-summary scope.

- **P1 — Schema-valid output can still abort when mandatory M12 claims are inserted.** Provider
  output may contain 256 claims (`validation.py:282`). Every distinct factual claim citing an
  exact authority handle is classified as mandatory, even when several represent the same
  authority fact (`validation.py:430`). Missing status/badge claims are then inserted, and more
  than 256 mandatory representations raise instead of being deterministically deduplicated or
  salvaged (`validation.py:442`). Thus a valid 256-claim response can still terminate hierarchy
  processing after mandatory insertion.

The browser contract remains capped at 256 claims, and the manifest updates exactly the two
changed browser assets, `app.js` and `contract.js`. Byte-level hash recomputation and focused
pytest execution were rejected by the enforced read-only execution policy, so no Release-suite
or live-provider result is claimed.

### Verdict

**FAIL** — two unresolved P1 authority/acceptance regressions remain.

## Single corrective-cycle disposition

Commit `e0fd3bf3dba34a2d936028f3df8773e69d9fc1c8` was the one permitted correction after this
rereview. It requires a factual exact-M12 claim to cite only one exact authority child, preserves
inherited context scope in deterministic authority proxies, and deduplicates mandatory
representations by authority ID while salvaging invalid duplicates claim-locally. Three direct
regressions were added. The final focused set passed 70 tests, Release passed 966/7, private-scale
acceptance passed, and browser acceptance passed.

No second independent rereview was authorized, so these dispositions are local evidence and not an
independent final-head PASS.
