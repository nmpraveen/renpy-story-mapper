# M06.5 Final Independent Re-review

Review date: 2026-07-12

Task/source ID: `019f4d73-853a-7df2-a43a-47733dbafb95`

Review branch: `codex/m06-5-independent-review`

Original review base: `975fbecd88774bee47e727a0006c60050635d7b1`

Final corrective base: `372fe6e596ccc81fcfb6036e5e11b12297310069`

## Final recommendation

**PASS / SHIP M06.5.** The production create, refresh, unresolved-authority, draft review,
decision persistence, apply gating, pagination, Quit, security, packaging, and Windows CPython
3.12 checks pass. No P0, P1, or P2 finding remains. Two non-blocking P3 polish observations remain;
neither changes story authority, security, persistence, or project correctness.

No Ren'Py or game Python was executed. The review used temporary projects and repository synthetic
fixtures only. The canonical sample archive was not accessed. No AI provider was constructed or
invoked.

## Remaining findings by severity

### P0

None.

### P1

None.

### P2

None.

### P3 — cancelling the create destination picker produces an error toast

The production picker correctly returns a flat object with `selection_id: null` on cancellation.
`createFromSource()` detects the missing `targetId` and throws “The project destination is
unavailable,” which is caught and shown as a toast. This is safe and performs no project write,
but a user-initiated cancel would be cleaner as a silent return, matching the initial source and
open-project picker behavior.

### P3 — normal production load retains two console-noise entries

Chrome reports that the duplicate meta-delivered `frame-ancestors` directive is ignored (the same
directive in the HTTP response header remains effective) and reports a 404 for `/favicon.ico`.
These are polish issues, not CSP or application failures.

## Corrective finding resolution

### Create path — resolved

The initial production browser passed `target.id` even though the native save picker returns
`selection_id`, causing `POST /api/v1/projects/create` to omit `project_selection_id` and return
400. The final browser now selects `target.id || target.selection_id`, validates it, and submits
both opaque IDs.

Independent live evidence:

- actual production page, actual `LocalWebServer`, no mock mode;
- two native picker calls returned 200;
- `POST /api/v1/projects/create` returned 200;
- progress completed and the temporary `.rsmproj` was created;
- the Chrome page entered the real 11-node/44-edge story workspace; and
- the independent regression also created a separate temporary project directly through the
  production HTTP shapes.

### Refresh path — resolved

The initial browser had no reachable refresh action. The final frontend exposes a visible Refresh
button, `LocalApi.refresh()`, and a progress/poll/reload handler.

Independent live Chrome evidence recorded `POST /api/v1/projects/refresh` returning 200, two
successful progress polls, a bootstrap reload, and a refreshed story view. The independent test
also modified a temporary source and completed a real refresh through the HTTP service.

### Authoritative unresolved filter — resolved at `372fe6e`

The first corrective implementation derived `unresolved` only from presentation kind text. The
independent review found that the known unresolved `jump expression emergency_route` is presented
as kind `jump`, so it was incorrectly emitted as `unresolved: false`. This was confirmed and
corrected with a deterministic join from semantic authority through matching `graph_node_ids`,
with safe parent propagation and generation-keyed caching.

The final real-fixture regression proves all four required cases through the actual HTTP API:

- `emergency_route`: presentation kind remains `jump`, `unresolved` is true;
- normal literal `jump harbor_arrival`: `unresolved` is false;
- containing Level-2 event: `unresolved` is true; and
- containing Level-1 scene: `unresolved` is true.

The browser consumes only the explicit API boolean and removes flagged nodes and induced edges
when **Include unresolved** is cleared.

### Draft review/apply/discard — resolved

The final API returns pending drafts only, including persisted per-arc/event decisions. The exact
review mutation uses `draft_id`, `target_kind`, `target_id`, and `decision`. Apply returns 409
`draft_review_incomplete` before every candidate is explicitly decided.

The independent backend regression created a real pending candidate without a provider, verified
the initial apply rejection, persisted every arc/event approval through the production review
route, reopened the pending payload, verified the decision count, and applied successfully. The
full suite separately covers discard and pending-only behavior.

The final Chrome harness proves deterministic review bounds:

- page size is 40 rows;
- an 85-candidate review persists 85 decisions;
- Apply is initially disabled and becomes enabled only after all decisions;
- page 3 contains exactly 5 rendered rows; and
- the request-key contract is exact.

## Security and lifecycle results

No security regression was found:

- bind validation permits only exact IPv4 `127.0.0.1` on an ephemeral port;
- exact `Host: 127.0.0.1:<port>` prevents hostname/DNS-rebinding aliases;
- API session, exact loopback Origin, and CSRF rules reject invalid combinations;
- tokens remain in the no-store root document and never enter URLs, state, or API payloads;
- CSP and related response headers are restrictive and runtime assets are local-only;
- decoded traversal, backslash, NUL, ambiguous dot segments, and static-root escape are rejected;
- JSON mutations require the correct content type, bounded valid Content-Length, UTF-8, and an
  object body; the one-MiB bound is enforced before reading;
- routine error bodies are generic and path-redacted;
- opaque picker UUIDs prevent browser filesystem authority;
- bootstrap, recent, story, evidence, facts, review, and diagnostics responses expose no absolute
  project path; evidence source paths remain project-relative;
- state uses same-directory temporary files and atomic replacement;
- the raw-socket independent test confirms `Connection: close` is enforced even when two
  keep-alive requests are pipelined;
- persistent-client shutdown and explicit Quit tests pass;
- cancellation sets the active task event and closes the single-worker executor; and
- project create/open/refresh, view, evidence, facts, and diagnostics perform no implicit provider
  construction. Chrome acceptance reports zero organization starts and zero remote requests.

## API and browser integration results

The actual production browser and loopback service successfully completed:

- source picker → destination picker → create → progress → workspace;
- Refresh → progress → bootstrap → refreshed view;
- opaque recent-project open and reopen;
- bounded Level 1 Arcs, Level 2 Events, and Level 3 Evidence traversal;
- search/focus, authoritative unresolved filtering, facts, and exact evidence calls;
- deterministic bounded nodes/edges and keyboard graph selection;
- responsive 100% and 200% event views;
- pending draft review, exact decision payloads, persisted review state, apply gating, apply, and
  discard contracts; and
- diagnostics showing `provider_requests_on_open: 0`.

The final nine-state Chrome harness passed Welcome, Create, Refresh, Progress, Events at 100% and
200%, Evidence, Review, and 85-candidate Review Pages. Every state exited 0, remained within the
240-item presentation boundary, and made zero remote requests.

## Packaging results

- Two clean isolated wheel builds succeeded and were byte-identical.
- Final wheel: 290,875 bytes.
- SHA-256 for both builds:
  `46189715ce1e5e212cc0d59e3d872da4f7e0d6b4ae9f66af81db767d69608ff2`.
- Normalized wheel timestamps were `2020-02-02 00:00:00`.
- The wheel contains `index.html`, `styles.css`, `app.js`, `api.js`, `contract.js`, `graph.js`,
  `mock-api.js`, `API_CONTRACT.md`, and `asset-manifest.json`.
- The portable `sha256-utf8-lf` manifest passed native LF and simulated CRLF verification.
- Wheel entry points include
  `renpy-story-mapper-web = renpy_story_mapper.web.launcher:main`.
- Both the installed Windows console entry point and `python -m` launcher returned help with exit
  0 from the CPython 3.12 installation.

## Commands and exact results

| Command | Exit | Result |
|---|---:|---|
| `$env:QT_QPA_PLATFORM='offscreen'; py -3.12 -m pytest` | 0 | 407 passed |
| `py -3.12 -m pytest tests\\test_m06_5_independent_review.py -q` | 0 | 4 passed in 3.10s |
| `py -3.12 -m ruff check .` | 0 | All checks passed |
| `py -3.12 -m mypy` | 0 | No issues in 50 source files |
| `py -3.12 -m pip check` | 0 | No broken requirements |
| `git diff --check` | 0 | No whitespace errors |
| `py -3.12 scripts\\m06_5_browser_acceptance.py --output <temporary>` | 0 | 9 Chrome states passed; remote_requests=0 |
| Playwright actual production create/refresh session | 0 | Create and refresh both returned 200 and completed |
| Two `py -3.12 -m build --wheel --outdir <temporary>` runs | 0 | Both built; hashes identical |
| Wheel listing, manifest, and entry-point inspection | 0 | All required browser assets and entry point present |
| `renpy-story-mapper-web --help` | 0 | Windows CPython 3.12 console entry point launched |
| `py -3.12 -m renpy_story_mapper.web.launcher --help` | 0 | Module entry point launched |

## Risks and limitations

- Native Windows dialogs were replaced with a deterministic narrow dialog adapter for automated
  browser actions; the Qt dialog implementation was inspected but not manually clicked.
- The browser acceptance harness uses the shipped mock adapter to generate deterministic visual
  states. Actual-server Chrome checks independently covered production create and refresh, while
  actual-server pytest covered authoritative unresolved and draft persistence/apply.
- A real provider-backed organization run was intentionally not started. Drafts were constructed
  locally through the accepted deterministic storage contract, so no story data left the machine.
- The review does not claim protection from a malicious local administrator, browser extension,
  or process already able to inspect the user's browser profile or process memory.

## Unresolved items

No M06.5 correctness, security, packaging, or acceptance blocker remains. The two P3 polish items
above may be handled opportunistically without delaying M06.5 shipment.
