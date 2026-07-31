# M15.1 Phase 05 - Whole-game reader correction plan

Updated: 2026-07-31

Status: implementation in progress; Gate 0 cross-label topology proof active

## Outcome

Turn the current whole-game checkpoint into the intended desktop story reader: a clean scrolling
timeline where downstream story events remain beneath the route that reaches them, conditions and
destinations use story language, earlier state causes are linked, expanded prose uses the available
reading width, and completed projects do not show dead workflow controls.

This plan covers the five remaining product corrections. It does not rebuild the parser, canonical
graph, corridor packetizer, AI transport, database, or project format.

## Why this order is fixed

1. Compose cross-label route topology.
2. Replace machine-facing text with story language.
3. Add state provenance and destination links.
4. Correct route disclosure and expanded-detail layout.
5. Remove dead workflow chrome and repair small accessibility/recent-project issues.

Topology comes first because names and state links need the true owning route. The reader layout
comes after the additive route contract is frozen so the frontend is not rebuilt twice. The first
proof is one real fitting-room route; whole-game regeneration waits until that proof is useful.

## Baseline that must not regress

At the reader projection, preserve:

- 111 story events;
- 594 reader-visible corridors, each attached exactly once;
- 260 default-reader controls and 571 default-reader arms;
- all current `continues`, `rejoins`, `ends`, and `unresolved` classifications; and
- the complete Python authority of 324 controls and 700 arms, including secondary technical detail.

Original game inputs remain read-only. Proofs and regenerated review projects use a disposable copy.
AI may name or explain Python-built facts, but it may not change ownership, membership, edges,
conditions, assignments, destinations, or rejoins.

## 1. Compose cross-label routes into the arm that reaches them

### Problem

The reader currently constructs every label as a peer event. Arm ownership is determined only inside
the label containing the split, so a jump or call into another label loses its route owner. In the
fitting-room example, the event reached only through `Keep arguing with her` is rendered after both
sibling arms and reads like shared chronology.

### Implementation

1. Read the existing graph and `label_transitions`; do not infer cross-label flow from captions.
2. Classify real label transfers as jump/fallthrough, call/return, unique route entry, shared entry,
   demonstrated rejoin, loop/revisit, or unresolved dynamic destination.
3. Build one canonical event prototype per label before assigning presentation ownership.
4. Carry the active arm lineage across label edges:
   - jumps and fallthrough retain the current owner;
   - calls place the called story beneath the calling route and returns resume the caller;
   - a uniquely reached label belongs beneath its proven incoming arm;
   - a label reached by sibling routes becomes one shared continuation after those routes;
   - repeated or looping entries render a link/reference instead of recursively copying the event;
   - ambiguous dynamic ownership remains explicitly unresolved.
5. Add one optional ordered route-flow field to an arm in the existing page-v1 contract. Use ordered
   route items if real call/return flow can interleave events and references; use a simpler event list
   only if the classification proves whole-event append order is sufficient.
6. Move each event into exactly one canonical tree location. Secondary entries point to that event by
   stable selection ID.
7. Update rendering, search, story index, event numbering, and reader-count traversal to recurse into
   arm-owned route flow. A search result or index jump opens all collapsed ancestors.

This is an additive reader-projection change. It does not require a new HTTP route, API version,
database table, migration, job, or provider layer.

### First real proof

Use the fitting-room chain containing `Push her out`, `Keep arguing with her`, the called argument
label, and their later shared continuation.

The proof passes when:

- the called fitting-room event appears only beneath `Keep arguing with her`;
- `Push her out` visibly bypasses it;
- the shared continuation appears exactly once;
- no duplicate copy remains as a peer top-level event;
- call/return order remains factual;
- loops produce references rather than recursive DOM; and
- recursive reader counts remain unchanged.

If the real graph exposes an entry with multiple ambiguous owners and no demonstrated rejoin, render
an unresolved/reference node and stop that case rather than guessing.

## 2. Replace visible code and machine labels with story language

### Problem

Default headlines and route rows still expose raw conditions, underscored labels, mechanical shared
continuation names, and bare `Otherwise` captions. Splitting identifiers on underscores does not
produce a human story name.

### Implementation

1. Add one backend story-name resolver used by events, controls, arms, destinations, and rejoins.
2. Resolve names in this order:
   - accepted reader-specific name keyed by stable structural ID;
   - existing AI corridor title for the exact target;
   - owning event or scene title;
   - first readable narration or dialogue in the destination corridor;
   - explicit `Unnamed story route` or `Unresolved destination` fallback.
3. Never create a visible name by splitting an identifier or appending `continuation` mechanically.
4. Keep raw labels, expressions, source lines, and bindings in `Python detail`, not in the default
   story surface.
5. Give each game condition a human question and each arm an explicit story outcome. `Otherwise`
   becomes what that route actually does, while the raw fallback expression remains technical evidence.
6. Keep two independent semantic facts:
   - who decided: player choice or game check;
   - where the route goes: continues, rejoins, ends, or remains unresolved.
7. Produce an inventory of only the structural IDs still lacking a safe deterministic name. Each AI
   packet includes the ID, kind, expression/label, assignment sites, nearby story context, and incoming
   and outgoing story titles. AI returns wording only.
8. Inspect the first 10 unresolved names in the coordinator. Only after that rendered canary is useful
   may the remainder be split across user-visible Sol/High Codex tasks.

### Acceptance

Scan structured user-visible fields, excluding technical disclosures, and require:

- zero underscored machine identifiers;
- zero raw comparison or boolean expressions;
- zero `Routes: Check whether` headings;
- zero mechanical `Shared ... continuation` names;
- zero exact bare `Otherwise` captions; and
- zero doubled fallback suffixes.

Every raw expression and source location remains available in `Python detail`.

## 3. Add state provenance and clickable route links

### Problem

Later state gates currently show variable names inside a warning disclosure. They do not identify or
link to the earlier choice or assignment that established the state. Destination and rejoin names are
also plain text instead of navigation targets.

### Implementation

1. Reuse the existing assignment and state-read facts to build an index by variable, graph node,
   source line, owning event, owning arm, operation, and route lineage.
2. For every condition arm, walk backward from each `state_read` and find earlier path-compatible
   assignments.
3. Remove assignments that occur after the condition or inside mutually exclusive sibling routes.
4. Map each surviving assignment to the closest visible event or arm and classify the relationship:
   - `Set earlier by` for one exact path-proven source;
   - `Can be set earlier by` for multiple compatible sources;
   - `Unresolved earlier state` when Python cannot prove the source safely.
5. Add optional structured backlink data containing the variable, relationship strength, target
   selection ID, human target title, and source reference. Keep raw variables in technical detail.
6. Add stable target IDs to destination and rejoin facts as well.
7. Centralize navigation so a backlink, destination, or rejoin click:
   - opens all ancestor disclosures;
   - reveals a target hidden by the current search state;
   - scrolls and focuses the target;
   - briefly highlights it; and
   - preserves enough navigation state for Back to return to the origin.
8. Rename ordinary technical evidence from `warning` to `Python detail`. Reserve warning styling for
   genuinely unresolved behavior.

### Proofs and acceptance

- The later `branch_9` checks link to the earlier player decision that establishes their value.
- The accepted Terrance variables `ter`, `loi`, and `terrance_answer_4_1` retain their correct sources.
- A condition never links to a future assignment or an incompatible sibling route.
- Every state-reading route has a valid backlink or an explicit unresolved provenance result.
- Every destination, rejoin, and provenance target exists and opens correctly in the rendered reader.

## 4. Correct nested-route disclosure and full-width expanded prose

### 4A. Closed nested routes

The stylesheet currently forces a direct child story sequence to `display: grid` even when its parent
`details` element is closed.

Change the layout rule so only an open descendant route receives grid display. Closed direct content
and its continuation stay hidden. Search, index jumps, destination links, and provenance links may
open the required ancestors programmatically.

Acceptance:

- closed descendant content has no visible height;
- mouse and keyboard activation open and close it reliably;
- opening one route does not alter unrelated siblings; and
- hidden story content remains searchable and navigable.

### 4B. Full-width selected-arm detail

Expanded prose is currently a child of one arm card, so CSS cannot make it span the sibling arm grid.
Restructure each choice into:

1. control heading;
2. sibling arm-card grid;
3. one shared full-width route-detail slot; and
4. descendant route content.

Activating an arm fills the shared slot with that arm's concrete prose, effects, and Python detail.
The slot appears below all siblings, `aria-expanded` reflects its state, a second activation closes it,
and selecting another arm replaces it without a large scroll jump. The slot spans the route group,
while prose remains capped near `68ch` for readable line length.

Acceptance at the user's desktop width and a narrower desktop window:

- selected detail starts below the full sibling row;
- its container uses the route-group width rather than one card's width;
- text remains comfortably readable;
- nested choices behave the same way;
- switching detail preserves the reader's place; and
- the page and story scroller have no horizontal overflow.

## 5. Remove dead workflow chrome and repair small reader polish

### Completed-story workflow chrome

Centralize the visibility of generation controls:

- no story yet: show Generate;
- active generation: show progress and Cancel;
- failed but resumable: show Retry or Resume;
- completed story with no active/resumable work: hide the disabled Generate button and empty
  readiness/progress bar.

If regeneration remains supported, place it in an intentional action rather than leaving a disabled
hero control above the story.

### Accessibility state

- Remove `aria-selected` from ordinary story buttons.
- Use `aria-expanded` for controls that reveal detail.
- Use `aria-current` only for the current story location and `aria-pressed` only for a genuine toggle.
- Keep internal selection in application state or a data attribute rather than using ARIA as storage.
- Preserve visible keyboard focus and current-selection navigation.

### Recent-project disambiguation

Show the smallest useful distinguishing context: project name, source basename, and precise
last-opened time. If those still collide, add a short parent-folder name or short project identifier.
Use an existing recent-project response field when available; otherwise add only the basename to the
existing response. Do not add a new endpoint or display full absolute paths in the normal card.

### Acceptance

- a completed project opens close to the story without dead controls;
- generation actions appear only when actionable;
- no ordinary story button uses `aria-selected`;
- keyboard detail and navigation behavior still works; and
- duplicate recent projects can be distinguished before opening them.

## Delivery gates

| Gate | Deliverable | Evidence required before continuing |
|---|---|---|
| 0 | Cross-label transfer classification and minimal additive contract | No ownership case is silently guessed |
| 1 | Fitting-room topology proof | Correct owning arm, bypass, shared continuation, counts, and rendered user review |
| 2 | Whole-game topology regeneration | Recursive totals and Python classifications unchanged |
| 3 | First 10 human-name canary | Useful rendered wording before any bulk naming |
| 4 | Whole-game names and provenance | No machine fallback on the default surface; links resolve correctly |
| 5 | Disclosure, detail-width, workflow, ARIA, and recent-project corrections | Focused desktop browser acceptance |
| 6 | Disposable final review project | User accepts the complete scrolling story before broad CI or shipping work |

After Gate 1 freezes the additive route contract, independent implementation may be split into
bounded user-visible `gpt-5.6-sol` High tasks: naming, provenance, and frontend rendering/polish. The
coordinator retains topology ownership, integration, and final browser acceptance.

## Primary implementation seams

| Area | Primary files |
|---|---|
| Route composition | `src/renpy_story_mapper/story_map_v2/whole_game_reader.py`, `whole_game_skeleton.py`, `scripts/m15_phase05_whole_game_reader.py` |
| Names and condition captions | `src/renpy_story_mapper/story_map_v2/whole_game_reader.py` and the existing summary/name artifact |
| Provenance | `whole_game_reader.py`, `whole_game_corridors.py`, and reusable logic from `progressive_story.py` |
| Page contract | `src/renpy_story_mapper/web/static/contract.js` |
| Recursive reader and navigation | `src/renpy_story_mapper/web/static/app.js` |
| Disclosure/detail layout | `src/renpy_story_mapper/web/static/styles.css` |
| Completed-story shell | `src/renpy_story_mapper/web/static/index.html`, `app.js`, and `styles.css` |
| Focused validation | `tests/test_story_map_v2_whole_game_reader.py`, focused cases in `tests/test_story_map_v2_phase03_track_b.py`, and `tests/test_m08_web_only_product.py` |

Static asset changes must update `src/renpy_story_mapper/web/static/asset-manifest.json` using the
repository's canonical UTF-8/LF hashes.

## Focused validation

During implementation, run only the changed seam's checks:

```powershell
$env:PYTHONPATH='src'
& .\.venv\Scripts\python.exe -m pytest tests\test_story_map_v2_whole_game_reader.py -q
node --check src\renpy_story_mapper\web\static\app.js
& .\.venv\Scripts\python.exe -m pytest tests\test_m08_web_only_product.py -q
```

Add focused contract and progressive-reader selectors from
`tests/test_story_map_v2_phase03_track_b.py`. The decisive check is the regenerated real-game reader
at 1920x1080: correct membership, nesting, state back-links, destinations, rejoins, readable prose,
working search/navigation, and no horizontal overflow or console errors.

Broad CI, Release, packaging, repeated review, storage optimization, and PR preparation wait until
the user accepts the rendered story or explicitly asks to ship it.
