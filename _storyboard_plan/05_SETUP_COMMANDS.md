# Setup commands

## Recommended: same repository, separate worktree folder

From the current project folder:

```bash
git status
```

Commit or stash unfinished changes. Then:

```bash
git worktree add ../renpy-story-mapper-ai -b ai-storyboard-v2
cd ../renpy-story-mapper-ai
mkdir -p _storyboard_plan
```

Copy the contents of this prompt pack into `_storyboard_plan/`.

Your directory should look roughly like:

```text
renpy-story-mapper-ai/
  _storyboard_plan/
    00_PRODUCT_AND_ARCHITECTURE.md
    01_CODEX_MASTER_PROMPT.md
    02_PHASE_01_CANARY_PROMPT.md
    ...
  src/
  tests/
  pyproject.toml
```

Start one Codex task in `renpy-story-mapper-ai`, paste `01_CODEX_MASTER_PROMPT.md`, then paste `02_PHASE_01_CANARY_PROMPT.md` after the readiness report.

## Simpler fallback

If you do not want to use a worktree, stay in the existing folder and create a branch:

```bash
git switch -c ai-storyboard-v2
```

The worktree approach is safer because the stale version remains physically separate and easy to compare.
