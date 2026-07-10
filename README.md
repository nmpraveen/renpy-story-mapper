# Ren'Py Story Mapper — Phase 1 Analyzer

This repository contains the Phase 1 proof for a future local-first Windows story mapper. It
inspects RPA 3.0 archives without extracting them, prefers available `.rpy` source over `.rpyc`,
and emits a source-linked directed control-flow graph. It does **not** initialize Ren'Py, import a
game, execute init/Python/creator code, evaluate script expressions, or decompile compiled scripts.

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

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
```

## Semantic story boundaries

Semantic grouping is deterministic and local. It does not use AI, execute story code, evaluate
conditions, or invent dynamic targets. Adjacent dialogue and narration are grouped only when the
Phase 1 graph proves an unambiguous fallthrough. Choices, conditions, jumps, calls, returns,
endings, unresolved behavior, and label boundaries remain explicit.

## Phase 1 boundaries

Supported graph authority: labels, fallthrough, string-literal menu choices, if/elif/else, jump,
call, return, and explicit unresolved nodes. The parser is deliberately conservative. It does not
attempt full Ren'Py language compatibility, `.rpyc` decompilation, expression truth evaluation,
creator-defined statement parsing, Python control-flow inference, screen/ATL analysis, or game
execution. Interactive `call screen` statements therefore retain sequential fallthrough plus an
explicit unresolved-interaction edge. Those boundaries are security properties, not missing
runtime dependencies.

Phase 2 may add an import worker/API and local desktop visualization over these JSON contracts. It
should continue treating the analyzer as a non-executing process and must not add AI summarization
or creator-code execution implicitly.
