# M02 Goal - Semantic Scenes and Story Beats

## Objective

Convert the established Phase 1 source-linked statement graph into deterministic, readable
narrative beats and scenes without AI and without executing Ren'Py or game Python.

## Deliverables

- A semantic model for story beats, scenes, boundaries, provenance, and classifications.
- Deterministic grouping of adjacent dialogue and narration.
- Beat boundaries at choices, conditions, jumps, calls, returns, endings, and structural labels.
- Preservation of characters, dialogue, narration, conditions, typed graph relationships, source
  files, and physical-line ranges.
- Conservative narrative-versus-utility label classification where static evidence is sufficient.
- Explicit unreachable content and unresolved dynamic transitions.
- Deterministic semantic JSON and CLI output.
- Representative fixtures and behavioral tests.
- Independent correctness review of the integrated implementation.
- Complete Windows verification, completion report, and native-generated infographic.
- One M02 milestone PR, left unmerged pending explicit user approval.

## Acceptance criteria

- Identical input produces byte-identical semantic output.
- Every beat maps to exact physical source lines.
- Choices and conditions retain their source-linked graph edges.
- No AI, cloud story-text transfer, or game-code execution is required.
- Existing Phase 1 behavior remains compatible.
- Every worker diff is inspected and integrated on the milestone branch.
- No critical correctness-review findings remain.
- Pytest, Ruff, strict mypy, `pip check`, and milestone-specific end-to-end checks pass on Windows.
- The canonical sample remains unchanged if accessed.
- `TASKS.md`, `COMPLETION_REPORT.md`, and `INFOGRAPHIC.png` exist.
- The M02 PR is ready for user review and no M03 work has begun.

## State

Active. Created after explicit user approval on 2026-07-10.
