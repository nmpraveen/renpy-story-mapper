# Ren'Py Story Mapper - Windows Master Plan

## 1. Purpose

Build a Windows-only application that reads Ren'Py scripts without executing game code, reconstructs the story as a source-linked branching graph, groups the graph into readable story beats, and optionally uses AI to summarize and explain the story.

This document is the permanent source of truth for the project. One main Codex task acts as the orchestrator. It works on one milestone at a time and creates separate local Codex tasks for major implementation, testing, review, or documentation work.

## 2. Established baseline

- Repository: `nmpraveen/renpy-story-mapper`
- Phase 1 PR: `#1`
- Baseline commit: `0ef367e5085cabb3c9e1a0ea31e4bb2b31334dcc`
- Platform and runtime authority: Windows only
- Python: CPython 3.12
- Canonical read-only sample:
  `C:\Users\prave\University of Michigan Dropbox\Praveen Manivannan\Windows Mac portal\scripts.rpa`

Phase 1 established the read-only RPA inventory, safe Ren'Py parser, source precedence, control-flow graph, diagnostics, CLI, and automated tests. Treat this as the accepted foundation. Do not repeat a standalone Phase 1 audit unless later changes require regression testing.

## 3. Product principles

1. The original game and archive are always read-only.
2. Never execute embedded Ren'Py, screen, or game Python code.
3. Deterministic analysis owns story structure. AI never invents graph edges.
4. Prefer `.rpy` when matching `.rpy` and `.rpyc` files both exist.
5. Every structural result retains its source file and physical line evidence.
6. Unknown dynamic behavior is classified as unresolved rather than guessed.
7. Local analysis works without an AI provider or internet connection.
8. Story text is not sent to a cloud AI provider unless the user enables it.
9. Windows is the only supported runtime and release platform for now.
10. Work on exactly one approved milestone at a time.

## 4. Technical architecture

```text
Game folder or scripts.rpa
        |
Read-only archive inventory
        |
Prefer .rpy over matching .rpyc
        |
Safe static Ren'Py parser
        |
Source-linked control-flow graph
        |
Semantic scenes and story beats
        |
Optional AI enrichment
        |
Windows story explorer and exports
```

The underlying result is a graph, not always a tree. Story routes can split, merge, loop, call shared labels, and return. The application may show a tree-like route view, but it must preserve the accurate graph underneath.

### Core data model

The internal project format should use SQLite, with JSON export when useful. Principal records include:

- Source file and physical line
- Label
- Dialogue and narration beat
- Scene
- Choice
- Condition
- Jump
- Call and return
- Natural fallthrough
- Ending
- Unresolved dynamic construct
- Character
- Typed graph edge
- AI summary and its provenance

### Planned Windows stack

- Python 3.12
- Existing analyzer package as the core engine
- PySide6 for the Windows desktop application
- Embedded Cytoscape.js with ELK layout for graph visualization
- SQLite for analyzed projects and caches
- PyInstaller for Windows distribution
- Provider adapters for optional OpenAI, Anthropic, xAI, and local OpenAI-compatible models

Electron, macOS support, game editing, and game patching are outside the current plan.

## 5. Permanent orchestration model

Create one permanent local Codex task named `RenPy Story Mapper - Orchestrator`. It owns:

- This master plan
- The active milestone self-goal
- Architecture and scope decisions
- Local worker-task creation and tracking
- Integration branches and conflict resolution
- Windows verification
- Completion reports
- Milestone infographic generation
- The approval gate before the next milestone

The orchestrator may make small integration fixes. Major independently reviewable work must be assigned to separate user-visible local Codex tasks, not merely simulated inside the orchestrator conversation.

### One self-goal per milestone

At the start of an approved milestone, the orchestrator creates exactly one active self-goal with that milestone's objective, deliverables, and acceptance criteria.

```text
PLANNED
  -> SELF-GOAL CREATED
  -> WORK PACKAGES DEFINED
  -> LOCAL TASKS CREATED
  -> IMPLEMENTATION AND REVIEW
  -> RESULTS GATHERED
  -> INTEGRATED
  -> WINDOWS VERIFICATION
  -> REPORT AND INFOGRAPHIC CREATED
  -> SELF-GOAL COMPLETED
  -> WAIT FOR USER APPROVAL
```

The next milestone goal must not be created until the current goal is genuinely complete and the user explicitly approves proceeding.

### Local worker-task rules

Create local Codex tasks only for substantial work such as:

- Core feature implementation
- A separate parser or graph subsystem
- Tests and representative fixtures
- Independent security or correctness review
- Desktop application components
- Packaging or release engineering
- Substantial documentation

Parallel tasks are allowed only within the currently active milestone and only when their work is independent. Use separate Git branches and worktrees when edits could collide. Assign non-overlapping files or clearly separated responsibilities.

Every worker brief must contain:

```text
Milestone:
Work package:
Repository and base commit:
Assigned branch or worktree:
Files or subsystem owned:
Required deliverables:
Required tests and evidence:
Explicit exclusions:
Read-only assets:
Completion-report format:
```

Every worker must return:

```text
Status: complete | partial | blocked
Branch and final commit:
Files changed:
Behavior implemented:
Tests run with exact results:
Known limitations:
Risks or unresolved questions:
Integration instructions:
Scope confirmation:
```

Worker tasks must not merge their own work, modify another worker's assigned files, start a later milestone, use destructive Git commands, or weaken acceptance criteria without approval.

### Orchestrator completion gate

A milestone is complete only when:

- Every required worker task has reported.
- The orchestrator has inspected the actual diffs and commits.
- Required work has been integrated on the milestone branch.
- Acceptance criteria are mapped to concrete evidence.
- Windows tests and checks pass.
- No critical review findings remain.
- The sample archive is proven unchanged if it was accessed.
- Documentation matches actual behavior.
- A detailed completion report exists.
- A native-image infographic has been generated and saved.

A worker saying "done" is not completion evidence by itself.

## 6. Milestone artifact structure

Use this structure in the project repository:

```text
docs/
  MASTER_PLAN.md
  milestones/
    M01/
      GOAL.md
      TASKS.md
      COMPLETION_REPORT.md
      INFOGRAPHIC.png
    M02/
      GOAL.md
      TASKS.md
      COMPLETION_REPORT.md
      INFOGRAPHIC.png
```

`TASKS.md` records task IDs, titles, ownership, branches, status, and final commits.

`COMPLETION_REPORT.md` records:

- Objective and scope
- Delivered behavior
- Architecture changes
- Worker contributions
- Commits integrated
- Commands, exit codes, and test counts
- End-to-end evidence
- Archive immutability evidence when applicable
- Known limitations and deferred work
- Readiness for the next milestone

After verification, the orchestrator must use Codex's native image-generation capability to produce `INFOGRAPHIC.png`. It must visually summarize the objective, components delivered, data flow, verified metrics, limitations, and what becomes possible next.

Do not substitute SVG, Mermaid rendering, Python drawing, a manually assembled graphic, or an external image API. If native image generation is unavailable, report that limitation instead of silently substituting another method. The Markdown completion report remains the factual source of truth because generated image text can be imperfect.

## 7. Milestones

### M01 - Phase 1 analyzer foundation

Status: Complete as the established baseline in open PR #1. Completion documentation and the
native-image infographic were added on 2026-07-10; the PR remains unmerged pending explicit user
approval.

Delivered foundation:

- Read-only RPA inspection
- Exact source inventory and precedence
- Safe static Ren'Py subset parser
- Labels, menus, conditions, jumps, calls, returns, and fallthrough
- Source-linked control-flow graph
- Diagnostics and unresolved classifications
- Deterministic CLI output
- Automated tests and quality checks

Bootstrap action: completed from the established evidence, with Windows regression verification
recorded in `docs/milestones/M01/COMPLETION_REPORT.md`. No duplicate standalone audit was performed.
Do not merge PR #1 without explicit user approval.

### M02 - Semantic scenes and story beats

Objective: convert the low-level statement graph into readable narrative units without using AI.

Deliverables:

- Group adjacent dialogue and narration into story beats.
- Split beats at choices, conditions, jumps, calls, returns, and endings.
- Group beats into scenes using labels and structural boundaries.
- Preserve characters, dialogue, narration, conditions, and source ranges.
- Distinguish narrative labels from shared utility labels where possible.
- Identify unreachable content and unresolved dynamic transitions.
- Produce deterministic semantic JSON and CLI output.
- Add representative fixtures and tests.

Acceptance criteria:

- Identical input produces byte-identical semantic output.
- Every beat maps back to exact source lines.
- Choices and conditions retain their graph edges.
- No AI or game-code execution is required.
- Existing Phase 1 behavior remains compatible.
- Pytest, Ruff, strict mypy, and `pip check` pass on Windows.

### M03 - Project persistence and incremental analysis

Objective: create a durable analyzed-project format that avoids repeating unchanged work.

Deliverables:

- SQLite project schema and migrations.
- Source, graph, scene, diagnostic, and metadata storage.
- Content-hash-based invalidation.
- Incremental reanalysis of changed sources.
- Project creation, reopen, refresh, and deletion commands.
- Safe cache and temporary-file handling.
- JSON import and export where appropriate.

Acceptance criteria:

- Closing and reopening preserves the same graph and scenes.
- Unchanged sources are not reparsed.
- Changed sources invalidate only dependent data.
- Database migrations are tested.
- Corrupt or incompatible projects fail safely.

### M04 - Windows desktop shell and graph explorer

Objective: provide a usable Windows application around the stable analyzer and project model.

Deliverables:

- PySide6 application shell.
- Game folder or archive selection.
- Read-only analysis workflow with progress and cancellation.
- Project open/reopen experience.
- Chapter and label overview.
- Progressive graph expansion rather than rendering all nodes at once.
- Source-evidence inspector.
- Search and diagnostic panels.
- Windows error reporting and logs.

Acceptance criteria:

- Application works on a clean supported Windows machine.
- Analysis remains responsive and cancellable.
- Large graphs open through aggregation and progressive expansion.
- Selecting a graph item reveals its source evidence.
- No writes occur in the game directory.

### M05 - AI enrichment

Objective: add optional provider-neutral story interpretation without allowing AI to control graph structure.

Deliverables:

- Provider-neutral AI interface.
- OpenAI, Anthropic, xAI, and local OpenAI-compatible adapters.
- Structured scene-summary schema.
- Summary, important events, characters, consequences, questions, tone, and confidence.
- Content-hash, model, and prompt-version caching.
- Cost and data-sharing confirmation before cloud requests.
- Windows Credential Manager integration for secrets.
- Retry, rate-limit, cancellation, and failure handling.

Acceptance criteria:

- The application remains fully usable without AI.
- AI cannot create or modify structural graph edges.
- Only explicitly approved text is sent to cloud providers.
- Repeated unchanged requests use the cache.
- Provider failure does not damage the analyzed project.

### M06 - Advanced story exploration

Objective: make complex routes understandable and answer practical story questions.

Deliverables:

- Selected-route tree view backed by the full graph.
- Choice comparison.
- Ending finder.
- Character timeline.
- Path explanation: "How did I reach this scene?"
- Consequence explanation: "What changes after this choice?"
- Search by label, dialogue, character, condition, or summary.
- Visible unresolved and dynamic behavior report.
- Initial symbolic route constraints where safely possible.

Acceptance criteria:

- Route views preserve merges, loops, calls, and returns accurately.
- User-facing explanations link to graph and source evidence.
- The application distinguishes proven facts from AI interpretation.
- Unsolvable dynamic routing is reported rather than fabricated.

### M07 - Export, packaging, and Windows release

Objective: deliver a distributable Windows application and portable story reports.

Deliverables:

- Interactive portable HTML report.
- JSON graph and semantic export.
- GraphML export.
- Markdown story outline.
- Optional printable route guide.
- PyInstaller Windows build.
- Portable and installer distribution options.
- Version metadata, release notes, and upgrade handling.
- Clear project and cache cleanup controls.

Acceptance criteria:

- End users do not need to install Python.
- Packaged analysis matches development output.
- Exported reports open without the original game.
- No credentials, source archive, caches, or temporary analysis files enter Git.
- Release publishing requires explicit user approval.

## 8. Git and scope rules

- Use a dedicated branch and PR for each milestone.
- Use isolated branches or worktrees for concurrent worker tasks.
- The orchestrator integrates worker commits in a controlled order.
- Do not merge PRs, publish releases, or force-push without user approval.
- Never commit credentials, `.venv`, the sample archive, extracted game content, caches, or temporary outputs.
- Preserve unrelated user changes.
- Run relevant tests after worker integration, not merely inside isolated tasks.
- Do not design or implement future milestones while the current milestone is active.

## 9. Ready-to-paste Windows orchestrator prompt

Copy everything inside the following block into one new permanent Codex task in the Windows `Renpy` project.

```text
You are the permanent lead orchestrator for the Windows-only Ren'Py Story Mapper project. This task owns the master plan and coordinates all future milestone work.

Read docs/MASTER_PLAN.md completely before acting and treat it as the project source of truth. If the file was placed at the repository root as MASTER_PLAN.md, move it into docs/MASTER_PLAN.md in the first milestone documentation work while preserving its contents.

Baseline repository: nmpraveen/renpy-story-mapper
Existing Phase 1 PR: #1
Baseline commit: 0ef367e5085cabb3c9e1a0ea31e4bb2b31334dcc

OPERATING MODEL

1. Remain the single permanent orchestrator task. Keep the master plan, milestone status, decisions, local task links, integration results, and final reports here.
2. Work on exactly one milestone at a time. Do not begin or implement the next milestone until I explicitly approve it.
3. At the beginning of each approved milestone, create exactly one self-goal containing that milestone's objective, deliverables, and acceptance criteria. Mark it complete only after integration, Windows verification, documentation, and the infographic are finished.
4. For major independent work, create user-visible local Codex tasks using the task/thread coordination tools. Use them for substantial implementation, tests and fixtures, independent review, packaging, or documentation. Do not substitute hidden or ephemeral subagents for the requested local tasks.
5. Give every worker task a bounded brief, base commit, assigned branch or worktree, owned files or subsystem, deliverables, tests, exclusions, and return contract. Use separate branches and worktrees where concurrent edits could collide.
6. Record every worker task's ID, title, responsibility, branch, and status in docs/milestones/<milestone-id>/TASKS.md. Monitor the tasks, answer questions, correct scope drift, and gather their final commits, diffs, tests, risks, and unresolved items.
7. A worker saying done is not proof. You own integration: inspect every delivered diff, resolve conflicts, run the milestone's complete Windows acceptance suite, and return defective work to the responsible task when appropriate.
8. After acceptance passes, update docs/MASTER_PLAN.md, write docs/milestones/<milestone-id>/COMPLETION_REPORT.md, and use Codex's native image-generation tool to create docs/milestones/<milestone-id>/INFOGRAPHIC.png. The infographic must summarize the objective, architecture or flow, major deliverables, verified metrics, limitations, and what becomes possible next.
9. Do not create the infographic with SVG, Mermaid rendering, Python drawing, manually composed shapes, or an external image API. The Markdown completion report remains the factual source of truth because generated-image text can be imperfect. If native image generation is unavailable, report that limitation rather than silently substituting another method.
10. Present the report and infographic, mark the milestone self-goal complete only when every required artifact exists, and stop. Wait for my explicit approval before creating the next milestone goal.

NON-NEGOTIABLE PRODUCT RULES

- Windows is the sole runtime and release authority. Use CPython 3.12 and Windows-native commands and paths. Do not spend time on macOS compatibility or use macOS results as proof.
- The canonical sample is read-only: C:\Users\prave\University of Michigan Dropbox\Praveen Manivannan\Windows Mac portal\scripts.rpa
- Never modify, replace, rename, unpack into, or write beside the sample. Put outputs in the repository worktree or a temporary directory. If a milestone reads it, record SHA-256, size, and LastWriteTimeUtc before and after.
- Never execute embedded Ren'Py or game Python. Static analysis only. Unknown dynamic behavior must be classified as unresolved.
- Deterministic code, not AI, owns labels, branches, conditions, jumps, calls, returns, fallthrough, source precedence, and source-linked graph edges.
- AI is optional enrichment only. Local analysis must work without it. Do not send story text to a cloud provider without explicit user enablement.
- Preserve .rpy precedence over matching .rpyc and retain source-file and physical-line evidence.
- Keep all work inside the active milestone. Do not implement UI, AI, packaging, or another future phase unless the active milestone explicitly includes it.
- Use one milestone branch and PR. Do not merge a PR or publish a release without explicit user approval.
- Never commit credentials, the sample archive, extracted game content, virtual environments, caches, or temporary outputs.

MILESTONE EXECUTION LOOP

A. Read the master plan and current Git state. Identify the first incomplete approved milestone and restate its scope and acceptance criteria.
B. Create that milestone's self-goal.
C. Break only major independent deliverables into local Codex worker tasks and track them.
D. Coordinate implementation and prevent scope expansion.
E. Gather all worker results and inspect their actual changes.
F. Integrate on the milestone branch.
G. Run the full Windows acceptance suite appropriate to the milestone. Include pytest, Ruff, strict mypy, pip check, and milestone-specific end-to-end checks. Record commands, exit codes, test counts, and deterministic outputs.
H. Recheck archive immutability if the sample was accessed.
I. Update the plan and completion report with deliverables, commits, worker tasks, verification evidence, limitations, and deferred work.
J. Generate the native-image infographic in the milestone folder.
K. Mark the self-goal complete, give me a concise handoff with artifact links, and stop for approval.

BOOTSTRAP NOW

1. Confirm that this is the Windows Renpy project and locate the repository checkout.
2. Confirm that docs/MASTER_PLAN.md or MASTER_PLAN.md is available. If neither exists, stop and ask me to place the file in the repository instead of inventing a replacement plan.
3. Treat M01 and PR #1 as the established Phase 1 baseline. Do not repeat a standalone audit.
4. Create the M01 completion documentation and native-image infographic from the established evidence only. Do not merge PR #1 without my approval.
5. Report that M02 - Semantic scenes and story beats is the next proposed milestone, including its suggested local task split and acceptance criteria.
6. Stop and wait for my explicit approval before creating the M02 self-goal or starting M02 implementation.
```

## 10. Suggested M02 worker split

When the user approves M02, the orchestrator should consider these local tasks:

1. `M02 - Semantic model and grouping engine`
   - Define the scene and beat schema.
   - Implement deterministic grouping and boundaries.

2. `M02 - Fixtures and behavioral tests`
   - Create focused Ren'Py fixtures.
   - Test dialogue grouping, menus, conditions, calls, returns, endings, and source ranges.

3. `M02 - Independent correctness review`
   - Review grouping semantics, provenance, determinism, and regression risks.
   - Make no implementation changes unless specifically reassigned.

The orchestrator owns CLI integration, conflict resolution, final Windows verification, milestone documentation, infographic generation, and the user approval gate.
