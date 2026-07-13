# M08 Worker Task Ledger

Baseline: `32e9a3c4a41c0eb4acc9b13af966f4b727319d46`

All normal implementation and review tasks use GPT-5.6 Sol with High reasoning and fast mode
disabled. GPT-5.6 Luna High is reserved for consented story-analysis calls made through the product
provider boundary.

| Task ID | Title | Responsibility | Branch | Status |
|---|---|---|---|---|
| `019f5bc1-a8ad-7c33-abf1-80c2db682291` | Remove desktop product surface | Delete the legacy standalone graph application and make the local browser the sole documented/shipped product surface | `codex/m08-web-only-cleanup` | Delivered `f703061`, correction `a10de95`; integrated as `a22850d`, `9529597`; milestone verification pending |
| `019f5bc1-a886-76d3-80e6-93db5308d8a3` | Build M08 evaluation core | Evaluation manifest, rubric, deterministic-versus-AI report contracts, non-live runner, fixtures, and tests | `codex/m08-ai-evaluation-core` | Delivered `a27b67c`; integrated as `5fd00af`; milestone verification pending |
| `019f5bcc-f66a-7d92-89e6-0a02eadc3bcc` | Add bounded AI windows | Exact narrative-window selection, hash-bound subset consent, bounded request assembly, resume/cache safety, and backend tests | `codex/m08-bounded-ai-windows` | Delivered `0c43f13`; integrated as `f2b685a`; browser contract update pending |
| `019f5bd6-d228-76f2-bb5f-862b2702420b` | Build AI Story Map projection | Deterministic quotient of validated AI groups into human story nodes/edges with exact detail/evidence links and technical fallback | `codex/m08-ai-story-projection` | Delivered `02b7bcc`; integrated as `77f6898`; web rendering pending |
| `019f5bde-6bf6-7153-a88f-8b90d1a370e5` | Integrate bounded web contract | Provider-free window resolution plus strict prepare/start HTTP and JavaScript contracts, restored browser workflow tests, and consent metadata | `codex/m08-web-bounded-contract` | Delivered `d687820`; integrated as `7390d7d`; orchestrator rerun 51 passed; milestone verification pending |
| `019f5bf4-3ee7-77b3-9cb2-532f179d8bb5` | Build AI Story Map browser UX | Browser-only quotient graph, two-level Detail/Evidence navigation, bounded consent workflow, progress/review/comparison UI, and Chrome acceptance harness | `codex/m08-browser-story-experience` | Delivered `3fa27ac`; integrated as `86f8af9`; 64-test combined M08 suite passed; milestone verification pending |
| `019f5c09-ba0e-70b1-9c6c-47bfbeb83590` | Fix bounded projection validation | Correct AI Story Map projection for mixed validated/fallback bounded-window assemblies while retaining untouched nodes as technical fallback | `codex/m08-bounded-projection-fix` | Delivered `91fc8c4`; integrated as `dd9debf`; focused tests passed and saved bounded MsDenvers projection is now available with unchanged authority hash |
| `019f5c15-9a9b-7bf0-8c07-16e1b6dc0a0b` | Review integrated M08 | Independent P0-P2 review of correctness, privacy, deterministic authority, exact consent, bounded projection, browser security, packaging, and acceptance completeness | `codex/m08-independent-review` | Complete at `8ebb0ae`: 510 tests passed; reported three P1 and two P2 findings; no review commit |
| `019f5c1d-8dc7-7342-9ee3-fcc8235a997d` | Close web safety gaps | Remove the superseded cloud-start bypass and separate current-run usage from persisted project history | `codex/m08-web-safety-fix` | Active corrective task from independent review |
| `019f5c1d-8dcf-78f3-96c0-66f8428b2b05` | Enforce evidence ownership | Reject AI claims that cite evidence belonging only to a different event/group while preserving deterministic evidence contracts | `codex/m08-evidence-ownership-fix` | Active corrective task from independent review |
| `019f5c1f-7508-7363-9621-26cb35d1cdbf` | Fix topology pagination | Return the complete bounded incident edge set for each AI Story Map node page and preserve explicit continuations | `codex/m08-topology-pagination-fix` | Active corrective task from independent review |

The permanent orchestrator owns integration, live AI authorization boundaries, complete Windows
acceptance, documentation, the native infographic, and the pull request.
