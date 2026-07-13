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
| `019f5bd6-d228-76f2-bb5f-862b2702420b` | Build AI Story Map projection | Deterministic quotient of validated AI groups into human story nodes/edges with exact detail/evidence links and technical fallback | `codex/m08-ai-story-projection` | Active |
| `019f5bde-6bf6-7153-a88f-8b90d1a370e5` | Integrate bounded web contract | Provider-free window resolution plus strict prepare/start HTTP and JavaScript contracts, restored browser workflow tests, and consent metadata | `codex/m08-web-bounded-contract` | Active |

The permanent orchestrator owns integration, live AI authorization boundaries, complete Windows
acceptance, documentation, the native infographic, and the pull request.
