# Ren'Py Story Mapper - Local Browser Story Map

This repository contains a local-first Windows browser application and analyzer for exploring
Ren'Py stories as a bounded, source-linked Route Map. It safely reads folders, individual source
files, or RPA 3.0 archives, prefers available `.rpy` source over matching `.rpyc`, stores durable
SQLite projects, and presents deterministic routes, choices, requirements, effects, and exact
evidence. It does **not** initialize Ren'Py, execute init/Python/creator code, or evaluate script
expressions. When original `.rpy` is unavailable, compiled `.rpyc` recovery uses an isolated,
pinned Unrpyc helper; its output is provenance-qualified reconstructed evidence and never original
author source or original physical-line authority.

## Safety model

- The RPA index is decompressed with explicit compressed/decompressed limits.
- Pickle globals and persistent IDs are rejected by a restrictive unpickler.
- Archive paths, chunk types, offsets, lengths, entry/chunk counts, per-entry sizes, and aggregate
  logical read work are validated.
- Source is decoded and streamed directly from the read-only archive; nothing is extracted beside
  the game.
- A purpose-built inert lexer/parser recognizes static built-in control flow. Python, creator
  statements, and unsupported blocks remain opaque and can produce unresolved graph nodes.
- Dynamic `jump expression` / `call expression` targets are retained as text but never evaluated.

The graph semantics follow Ren'Py's documented/official AST reachability model: ordinary
fallthrough, menu reunion plus possible no-choice fallthrough, conditional merges, static jump
transfer, call target plus an explicit return-site summary, and return edges from known callees.
The implementation is original and does not import or vendor the Ren'Py runtime.

References:

- <https://www.renpy.org/doc/html/label.html>
- <https://www.renpy.org/doc/html/menus.html>
- <https://github.com/renpy/renpy/blob/master/renpy/ast.py>
- <https://github.com/renpy/renpy/blob/master/renpy/parser.py>

## Windows setup

Requires CPython 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If PowerShell activation is disabled, invoke `.\.venv\Scripts\python.exe` directly as shown below.

## Local browser application

Launch the supported product after setup:

```powershell
.\.venv\Scripts\renpy-story-mapper-web.exe
```

Or double-click `Launch RenPy Story Mapper.cmd` in the repository folder.

The launcher binds an ephemeral port on `127.0.0.1`, opens the system browser, and serves only
packaged local assets. Use **Open Folder**, **Open Archive**, or **Open File** to select a read-only
game source and save the `.rsmproj` project outside the selected source folder. Use **Open Project**
for an existing project and **Refresh** after source changes. Native Windows dialogs remain a narrow
launcher implementation detail; selected filesystem paths are represented in browser requests by
short-lived opaque identifiers.

The browser has exactly two user-visible map levels:

- **Route Map:** a bounded chronological overview of story lines, choices, merges, loops,
  continuations, and endings.
- **Detail / Evidence:** the selected route element's local context, requirements, effects,
  unresolved behavior, exact source text, relative paths, and physical lines.

Pan, zoom, fit, paging, keyboard navigation, search, technical/unresolved toggles, and source
evidence all remain inside this two-level browser workflow. Optional organization proposes a more
readable story view without changing deterministic graph authority.

The deterministic technical map remains fully usable without AI or cloud access. See the
[local browser operations guide](docs/LOCAL_BROWSER.md) for launch, security, and shutdown details.

## Analyze an archive

Graph over all imported source labels, with reachability marked from `label start`:

```powershell
.\.venv\Scripts\python.exe -m renpy_story_mapper analyze `
  "C:\path\to\scripts.rpa" `
  --output-dir artifacts\sample `
  --entry-label start
```

Restrict label definitions to selected source files while retaining explicit out-of-scope boundary
nodes:

```powershell
.\.venv\Scripts\python.exe -m renpy_story_mapper analyze `
  "C:\path\to\scripts.rpa" `
  --output-dir artifacts\prologue-chapter-1 `
  --entry-label start `
  --scope-glob "*script.rpy" `
  --scope-glob "*chapter1*.rpy"
```

The output directory contains deterministic `import-manifest.json`, `story-graph.json`, and
`semantic-story.json` files. The semantic story groups source-linked dialogue and narration into
readable beats and label-based scenes while retaining structural transitions, reachability, exact
physical source ranges, and unresolved dynamic behavior.
The manifest includes every entry's path, uncompressed size, SHA-256, extension, source/compiled
pairing, selection reason, and a before/after archive-integrity check. The graph contains stable
node IDs, directed typed edges, exact source spans/text, diagnostics, unresolved reasons, and a
`reachable_from_entry` flag. Scoped graphs retain every label CFG in scope even when interactive or
dynamic behavior prevents proving a static path from `start`.

Inventory only:

```powershell
.\.venv\Scripts\python.exe -m renpy_story_mapper inspect `
  "C:\path\to\scripts.rpa" `
  --output artifacts\import-manifest.json
```

## Durable projects and story state

M03 stores authoritative analysis in a versioned SQLite project. The selected game folder or RPA
archive remains read-only, and the project path must be outside a selected game folder.

```powershell
.\.venv\Scripts\python.exe -m renpy_story_mapper project create `
  "C:\path\to\scripts.rpa" `
  "artifacts\projects\story.rsmproj"

.\.venv\Scripts\python.exe -m renpy_story_mapper project show `
  "artifacts\projects\story.rsmproj" `
  --output "artifacts\projects\story-snapshot.json"

.\.venv\Scripts\python.exe -m renpy_story_mapper project refresh `
  "C:\path\to\scripts.rpa" `
  "artifacts\projects\story.rsmproj"
```

Refresh compares SHA-256 source fingerprints, reuses cached parsed modules for unchanged files,
and reparses only changed source files. The project retains the M01 graph, M02 semantic layer,
diagnostics, unresolved records, deterministic requirements, explicit state effects, and the
state-variable registry. Simple literal assignments and numeric `+=`/`-=` effects are proven;
creator calls with visible literal arguments are possible effects; computed or dynamic behavior
remains unresolved. Every gate and effect retains its exact source path and physical lines.

Projects can be deleted explicitly after they are no longer needed:

```powershell
.\.venv\Scripts\python.exe -m renpy_story_mapper project delete `
  "artifacts\projects\story.rsmproj"
```

## Tests and static checks

Use the tiered Windows validation entry point for routine work:

```powershell
# Short edit loop: Ruff plus stable parser/semantic tests.
.\scripts\validate.ps1 -Tier Fast

# Scoped test selection; pass multiple targets as a PowerShell array.
.\scripts\validate.ps1 -Tier Focused `
  -PytestTarget tests\test_parser_graph.py,tests\test_semantic.py

# Full deterministic repository, static, package, and scale verification.
.\scripts\validate.ps1 -Tier Release

# Inspect commands and timeouts without executing them.
.\scripts\validate.ps1 -Tier Release -DryRun
```

`Release` discovers the complete pytest tree, packaged JavaScript, and deterministic
`*_scale_acceptance.py` scripts, so later milestone additions join the gate without editing the
orchestrator. It builds the wheel through pip's default isolated PEP 517 environment, installs it
into a temporary target, and verifies imports and packaged browser assets. Each command has a
bounded timeout; use `-TimeoutSeconds` only when a slower machine needs a deliberate override.

Real-browser acceptance is excluded by default. Request the newest committed browser harness with
`-Tier Release -IncludeBrowser`, or combine that switch with `-BrowserScript <path>`. Private-corpus
acceptance is never discovered or run by the entry point; invoke a private harness directly only
when its inputs are explicitly authorized and available.

The equivalent individual commands remain:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m mypy src\renpy_story_mapper
.\.venv\Scripts\python.exe -m pip check
```

## Semantic story boundaries

Semantic grouping is deterministic and local. It does not use AI, execute story code, evaluate
conditions, or invent dynamic targets. Adjacent dialogue and narration are grouped only when the
Phase 1 graph proves an unambiguous fallthrough. Choices, conditions, jumps, calls, returns,
endings, unresolved behavior, and label boundaries remain explicit.

## Current boundaries

Supported graph authority: labels, fallthrough, string-literal menu choices, if/elif/else, jump,
call, return, and explicit unresolved nodes. The parser is deliberately conservative. It does not
attempt full Ren'Py language compatibility, expression truth evaluation, creator-defined statement
parsing, Python control-flow inference, screen/ATL analysis, or game execution. Static `.rpyc`
recovery, when required, runs through the isolated pinned helper and records derivation provenance,
completeness, and reconstructed line basis; incomplete coverage remains explicit and gated by the
recovered-source acknowledgement policy. Interactive `call screen` statements retain sequential
fallthrough plus an explicit unresolved-interaction edge. Those boundaries are security properties,
not missing runtime dependencies.

The loopback browser is the sole supported product surface. The command-line analyzer remains a
diagnostic and export harness, not a second interactive product. The legacy QGraphicsView desktop
application is not packaged. Optional organization cannot change deterministic edges, gates,
effects, routes, endings, unresolved records, or source evidence. Hosted deployment, installers,
standalone executables, macOS support, game editing, and game patching remain out of scope.
