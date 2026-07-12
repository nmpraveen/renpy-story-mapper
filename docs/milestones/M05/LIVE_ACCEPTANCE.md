# M05 Live Acceptance Evidence

Date: 2026-07-11 America/New_York (runs persisted after midnight UTC)

This evidence uses only the repository-owned synthetic fixture. No Dropbox or canonical game
content was transmitted. Fresh per-run cloud confirmation was supplied to the workflow, which
invoked the isolated Codex CLI with `--model gpt-5.6-luna`, High reasoning, fast mode disabled,
read-only sandboxing, ephemeral state, and the packaged structured-output schema.

## Synthetic Luna run

The input was `tests/fixtures/m05/complex_branching/complex_story.rpy`, logical UTF-8/LF SHA-256
`383cdc77af981acf27f80c54d018060c126e6824f7bf29c2d6ec9a9a73fae650`. The deterministic project
contained 369 graph nodes, 408 graph edges, 212 semantic beats, 256 semantic transitions, 282
presentation nodes, 404 presentation edges, 26 requirements, 88 effects, and one explicitly
unresolved dynamic jump.

The fresh corrected-cache-identity run made 12 provider calls in 572.591 seconds, using 187,896
input and 30,200 output tokens. Every provider response passed its stage schema. Final local draft
validation then rejected duplicate event outcome values, safely creating no draft and changing no
accepted story organization. Commit `e8be732` added stable deterministic de-duplication plus a
regression test.

The immediate retry reused all 12 validated cache records and made zero provider calls. It
completed in 174 ms with pending draft `draft:2ddf780022c677a97eeefa88`: 33 events, four arcs, and
77 evidence-backed claims. The deterministic authority tables were byte-logically identical before
and after, with SHA-256
`337e5158a1d62d22b7ee76f68b2704b2077343f75e9a14e4781f61aad08ed618`.

The live invocation used Windows CPython 3.12 from `.venv` and called:

```text
OrganizationWorkflow(project, lambda mode: CodexCliProvider(mode)).organize(
    (), OrganizationOptions(), progress=..., cancelled=lambda: False,
    confirm_cloud=lambda run_id: True,
)
```

The persisted run IDs, draft ID, timing, usage, authority hash, and storage counts are retained in
`LIVE_ACCEPTANCE.json`. The `.rsmproj`, cache payloads, and generated story organization remain in a
temporary directory and are deliberately not committed.

## Cache and UI confirmation

An additional unchanged rerun again produced 12 cache hits, zero provider calls, the same 33-event,
four-arc, 77-claim draft shape, and the same deterministic-authority hash. The native Windows UI
harness opened the previously accepted live project without provider invocation, rendered 55
items, exposed exact source evidence, used an isolated INI settings file, and captured seven PNGs.
The screenshots are retained under `docs/milestones/M05/screenshots/`.

## Storage measurement

A fresh deterministic project built from the same fixture was 2,416,640 bytes. The live project
after repeated acceptance, cached reruns, retained drafts, and one accepted organization was
3,608,576 bytes: growth of 1,191,936 bytes, or 1.493x baseline. The live database contained 25
cache rows, nine run rows, 107 chunk rows, four draft rows, two accepted arcs, 24 accepted events,
71 accepted claims, and 129 claim-evidence links. M05 records this growth and defers compaction.

## Remaining acceptance boundary

The real `script small new.rpy` Dropbox smoke source has not been transmitted. It requires separate
explicit user consent immediately before that cloud run. The source will be fingerprinted before
and after, copied to a temporary input directory, and never modified or written beside.
