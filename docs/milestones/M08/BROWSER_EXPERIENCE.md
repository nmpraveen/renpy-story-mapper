# M08 browser story experience

The loopback browser now presents an applied **AI Story Map** by default. Its event boxes are
validated AI groups and its lines are deterministic quotient edges. **Technical Structure** is the
unchanged factual comparison and the automatic fallback when an applied assembly is missing,
stale, or invalid.

The product has two visible levels:

1. The broad map shows human event titles and summaries, chronological flow, local detours,
   persistent routes, loops, merges, endings, AI coverage, and technical fallback.
2. **Detail / Evidence** shows member technical nodes and edges, gates, effects, reviewer
   corrections and pins, evidence-backed claims, and relative qualified source lines. **Back to
   Route Map** is the only level transition.

AI Story Map paging is topology-complete for each bounded event slice. **Next** first walks every
incident-edge page for the same events with a slice-bound cursor, then advances to the next event
slice and resets that cursor. **Previous** replays the exact bounded cursor history. Every crossing
connection remains selectable through a labelled continuation portal backed by its real off-page
endpoint. Technical Structure keeps its independent comparison paging contract.

Organization is always bounded. **Use visible nodes** creates a provider-free exact narrative
window preview. **Preview AI scope** prepares that selection with finite time, token, and call
budgets. The consent dialog echoes all counts, boundary counts, IDs and hashes, recovered-source
acknowledgement, and the exact `gpt-5.6-luna` / High / fast-off profile. Start copies that prepared
binding unchanged. Opening, navigation, switching, preview, comparison, replay, and reopening do
not construct a provider.

Run the non-live real-browser acceptance from the repository root:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
py -3.12 .\scripts\m08_browser_acceptance.py --output .\artifacts\m08\browser
```

The harness creates a temporary local fixture and persisted mock organization, drives Chrome or
Edge at 100% and 200%, rejects non-loopback requests, and records deterministic screenshots plus a
JSON report. It never confirms the provider start action and makes no cloud or live-AI call.
